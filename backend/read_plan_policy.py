"""Narrow read-only explain policy and a metadata-only response boundary."""
import re
from typing import Literal
from pydantic import BaseModel, Field
from release_control import ReleaseBlocked

PlanKind = Literal["cohort", "latest", "ranking"]
SAFE_STAGES = {"$match", "$sort", "$project", "$group", "$replaceRoot"}
FORBIDDEN = {"$out", "$merge", "$lookup", "$unionWith", "$facet", "$graphLookup",
             "$where", "$function", "$accumulator"}
MAX_PLAN_MS = 2000


class IndexKey(BaseModel):
    field: str
    direction: int | str


class PlanIndex(BaseModel):
    name: str
    keys: list[IndexKey]


class PlanSummary(BaseModel):
    stages: list[str] = Field(default_factory=list)
    indexes: list[PlanIndex] = Field(default_factory=list)
    blocking_sort: bool = False
    collection_scan: bool = False


class ReadPlanResult(BaseModel):
    query: PlanKind
    observed_at: str
    mode: Literal["queryPlanner"] = "queryPlanner"
    trigger: Literal["manual", "timeout", "cancelled"] = "manual"
    status: Literal["available", "unavailable"]
    plan: PlanSummary | None = None
    applied_hint: str | None = None
    alternative_index: str | None = None
    alternative_plan: PlanSummary | None = None
    selected_hint: str | None = None
    installed_indexes: list[PlanIndex] = Field(default_factory=list)
    metadata_errors: list[str] = Field(default_factory=list)


def validate_pipeline(pipeline):
    if not isinstance(pipeline, list) or not 1 <= len(pipeline) <= 12:
        raise ReleaseBlocked("unsupported_read_plan")
    for stage in pipeline:
        if not isinstance(stage, dict) or len(stage) != 1 or next(iter(stage)) not in SAFE_STAGES:
            raise ReleaseBlocked("unsupported_read_plan_stage")
    def walk(value):
        if isinstance(value, dict):
            if FORBIDDEN.intersection(value):
                raise ReleaseBlocked("unsafe_read_plan_expression")
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
    walk(pipeline)


def safe_name(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.*$-]{1,120}", value) else "redacted"


def ordered_index(name, keys):
    pairs = keys.items() if isinstance(keys, dict) else keys
    return PlanIndex(name=safe_name(name), keys=[IndexKey(field=safe_name(k), direction=v)
        for k, v in pairs if v in (1, -1, "hashed", "text", "2dsphere", "2d")])


def summarize_plan(raw):
    """Only winning plans; never raw filters, bounds, URI, rejected plans or IDs."""
    out = PlanSummary()
    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            stage = node.get("stage")
            if isinstance(stage, str) and re.fullmatch(r"[A-Z0-9_]{1,64}", stage):
                out.stages.append(stage)
            if isinstance(node.get("keyPattern"), dict) and isinstance(node.get("indexName"), str):
                out.indexes.append(ordered_index(node["indexName"], node["keyPattern"]))
            for key in ("queryPlan", "inputStage", "inputStages", "outerStage", "innerStage", "children"):
                visit(node.get(key))
            for shard in node.get("shards", []) if isinstance(node.get("shards"), list) else []:
                visit(shard.get("winningPlan") if isinstance(shard, dict) else None)
    visit(raw.get("queryPlanner", {}).get("winningPlan"))
    for stage in raw.get("stages", []):
        if not isinstance(stage, dict):
            continue
        for name in SAFE_STAGES.intersection(stage):
            out.stages.append(name)
        visit(stage.get("$cursor", {}).get("queryPlanner", {}).get("winningPlan"))
    if isinstance(raw.get("shards"), dict):
        for shard in raw["shards"].values():
            sub = summarize_plan(shard)
            out.stages.extend(sub.stages)
            out.indexes.extend(sub.indexes)
    out.blocking_sort = any(s in ("SORT", "$sort") for s in out.stages)
    out.collection_scan = "COLLSCAN" in out.stages
    return out