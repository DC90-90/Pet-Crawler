"""Bounded read-plan diagnostics; no data/index writes or scheduled tasks."""
import asyncio
import json
import logging
import time
from copy import deepcopy
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from weakref import WeakKeyDictionary

from read_plan_policy import MAX_PLAN_MS, PlanKind, ReadPlanResult, ordered_index, summarize_plan
from release_database import GuardedDatabase

logger = logging.getLogger(__name__)
_states = WeakKeyDictionary()
CAPTURE_INTERVAL_SECONDS = 300


async def fixed_pipeline(db, kind):
    if kind == "cohort":
        from price_cohort import snapshot_pipeline
        own = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1}, max_time_ms=MAX_PLAN_MS)
        active = await db.stores.distinct("id", {"is_active": {"$ne": False}, "id": {"$ne": (own or {}).get("id")}}, maxTimeMS=MAX_PLAN_MS)
        return snapshot_pipeline(active, datetime.now(timezone.utc))
    from snapshot_reads import latest_pipeline
    from store_views import ELIGIBILITY_FIELDS
    query = {"observation_version": 2, "is_synthetic": False}
    if kind == "ranking":
        query["crawled_at"] = {"$gte": datetime.now(timezone.utc)-timedelta(days=7)}
    return latest_pipeline(query, ELIGIBILITY_FIELDS if kind == "ranking" else None)


async def collect_read_plan(db, kind: PlanKind, *, generated_pipeline=None, after_timeout=False, applied_hint=None, trigger="manual"):
    guarded = db if isinstance(db, GuardedDatabase) else GuardedDatabase(db)
    from read_plan_policy import safe_name
    result = ReadPlanResult(query=kind, observed_at=datetime.now(timezone.utc).isoformat(), status="unavailable", trigger=trigger,
                           applied_hint=safe_name(applied_hint) if applied_hint else None)
    async def collect():
        pipeline = None
        try:
            pipeline = generated_pipeline if generated_pipeline is not None else await fixed_pipeline(guarded, kind)
            raw = await guarded.explain_snapshot_read(pipeline, hint=applied_hint)
            result.plan = summarize_plan(raw)
            if result.plan.stages:
                result.status = "available"
            else:
                result.metadata_errors.append("plan:UnrecognizedShape")
        except (Exception, asyncio.TimeoutError) as exc:
            result.metadata_errors.append("plan:"+type(exc).__name__)
        indexes = None
        try:
            indexes = await asyncio.wait_for(guarded.product_snapshots.index_information(), timeout=2)
            result.installed_indexes = [ordered_index(name, spec["key"]) for name, spec in indexes.items()]
        except (Exception, asyncio.TimeoutError) as exc:
            result.metadata_errors.append("indexes:"+type(exc).__name__)
        if indexes is not None and kind == "cohort" and pipeline is not None and result.status == "available" and not applied_hint:
            try:
                from snapshot_strategy import safe_store_index, select_after_timeout
                from read_plan_policy import safe_name
                used = {item.name for item in result.plan.indexes}
                candidate = next((name for name, spec in indexes.items()
                    if safe_store_index(spec) and name == safe_name(name)
                    and (after_timeout or name not in used)), None)
                if candidate:
                    raw_alternative = await guarded.explain_snapshot_read(pipeline, hint=candidate)
                    alternative = summarize_plan(raw_alternative)
                    result.alternative_index, result.alternative_plan = candidate, alternative
                    # Explain bypasses the plan cache: even the same fresh
                    # winning index may differ from the failed cached plan.
                    # Never force an ignored hint, blocking sort, or scan.
                    if (after_timeout and not alternative.collection_scan and not alternative.blocking_sort
                            and candidate in {index.name for index in alternative.indexes}
                            and select_after_timeout(db, candidate)):
                        result.selected_hint = candidate
            except (Exception, asyncio.TimeoutError) as exc:
                result.metadata_errors.append("alternative_plan:"+type(exc).__name__)
    try:
        await asyncio.wait_for(collect(), timeout=5)
    except TimeoutError:
        result.metadata_errors.append("diagnostic:TimeoutError")
    return result


def _enqueue_capture(db, kind: PlanKind, generated_pipeline, applied_hint=None, confirmed_timeout=True):
    """One capture per DB/kind/strategy/worker/5min. Never retries itself."""
    loop = asyncio.get_running_loop()
    state = _states.setdefault(loop, OrderedDict())
    raw = db.raw if isinstance(db, GuardedDatabase) else db
    key = (id(raw.client), raw.name, kind, applied_hint, confirmed_timeout)
    now = time.monotonic()
    old = state.get(key)
    if old and ((old[1] is not None and not old[1].done()) or now-old[0] < CAPTURE_INTERVAL_SECONDS):
        return
    if len(state) >= 32:
        for candidate, (_, task) in list(state.items()):
            if task is None or task.done():
                state.pop(candidate)
                break
        else:
            return
    async def capture():
        try:
            result = await collect_read_plan(db, kind, generated_pipeline=generated_pipeline,
                                             after_timeout=confirmed_timeout, applied_hint=applied_hint,
                                             trigger="timeout" if confirmed_timeout else "cancelled")
            logger.warning("ANALYTICS_READ_PLAN %s", json.dumps(result.model_dump(), separators=(",", ":")))
        except Exception as exc:
            logger.warning("ANALYTICS_READ_PLAN_UNAVAILABLE %s", type(exc).__name__)
    generated_pipeline = deepcopy(generated_pipeline)
    task = asyncio.create_task(capture())
    state[key] = (now, task)
    def completed(done):
        state[key] = (now, None)
        if not done.cancelled():
            done.exception()
    task.add_done_callback(completed)


def capture_after_timeout(db, kind: PlanKind, generated_pipeline, applied_hint=None, confirmed_timeout=True):
    # Diagnostics must never replace the original read failure, including with
    # test doubles, loop shutdown or unavailable metadata/driver capabilities.
    try:
        _enqueue_capture(db, kind, generated_pipeline, applied_hint, confirmed_timeout)
    except Exception as exc:
        logger.warning("ANALYTICS_READ_PLAN_UNAVAILABLE %s", type(exc).__name__)