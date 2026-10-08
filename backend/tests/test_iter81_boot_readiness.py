"""iter81 — the production rollout that never became ready.

Deploy attempt Sep 10 2026 failed with
`deployment failed to become ready: timeout waiting for the condition`, health
check never run. The startup handler AWAITED the whole boot sequence (seeds,
store registry, 35 index ensures, catalogue re-tag) before uvicorn served a
single request, and any exception in it made starlette abort the process with
"Application startup failed. Exiting." — on Kubernetes both modes look
identical: the readiness probe never passes and the rollout times out.

These fences pin the shape that cannot fail that way again.
"""
import asyncio
import os
import re
from pathlib import Path

import requests

import server

SRC = Path(server.__file__).read_text()


def _block(marker: str) -> str:
    return SRC.split(marker, 1)[1].split("\nasync def ", 1)[0]


# ── readiness: bind first, boot second ───────────────────────────────────────
def test_startup_handler_only_schedules_the_boot_sequence():
    handler = _block("async def startup(")
    assert "_boot()" in handler, "startup must schedule the background boot task"
    for forbidden in ("await seed_database()", "await seed_super_admin()",
                      "await ensure_stores()", "await ensure_all_indexes("):
        assert forbidden not in handler, (
            f"startup must not AWAIT {forbidden} — it blocks the readiness probe")


def test_boot_wrapper_swallows_every_exception():
    wrapper = _block("async def _boot(")
    assert "try:" in wrapper and "except Exception" in wrapper, \
        "a boot failure must never exit the process"
    assert "_boot_sequence()" in wrapper


def test_boot_sequence_phases_are_fail_soft():
    seq = _block("async def _boot_sequence(")
    assert "_wait_for_mongo()" in seq, "the boot sequence must wait for MongoDB first"
    for phase in ("seed_database", "seed_super_admin", "ensure_stores"):
        assert phase in seq, f"{phase} must still run at boot"
    assert "logger.exception" in seq, "each phase must log and continue"
    # the crawl-job registration is guarded too, so the scheduler still starts
    reg = seq.split("Register crawl jobs", 1)[1]
    assert "try:" in reg and "except Exception" in reg


def test_wait_for_mongo_retries_and_never_raises():
    stub_calls = {"n": 0}

    class _Admin:
        async def command(self, *_a, **_kw):
            stub_calls["n"] += 1
            raise RuntimeError("ServerSelectionTimeoutError (simulated cold Atlas)")

    class _Client:
        admin = _Admin()

    real = server.client
    server.client = _Client()
    try:
        ok = asyncio.new_event_loop().run_until_complete(
            server._wait_for_mongo(attempts=3, delay=0))
    finally:
        server.client = real
    assert ok is False, "an unreachable Mongo must be reported, not raised"
    assert stub_calls["n"] == 3, "every attempt must be made"


def test_wait_for_mongo_returns_true_on_the_live_database():
    ok = asyncio.new_event_loop().run_until_complete(
        server._wait_for_mongo(attempts=2, delay=0))
    assert ok is True


# ── boot resource spikes moved out of the readiness window ───────────────────
def test_playwright_self_heal_is_delayed_and_skips_when_healthy():
    seq = _block("async def _boot_sequence(")
    heal = seq.split("def _aggressive_playwright_self_heal(", 1)[1]
    assert "PLAYWRIGHT_SELFHEAL_DELAY_SECS" in heal, \
        "the ~400MB browser download must not start inside the readiness window"
    assert 'time.sleep(delay)' in heal
    assert '_smoke("pre-install")' in heal, \
        "a working headless launch must skip the install entirely"
    install_idx = heal.index("playwright\", \"install\"")
    assert heal.index('_smoke("pre-install")') < install_idx, \
        "probe BEFORE downloading, not after"


def test_cache_warm_up_is_delayed():
    seq = _block("async def _boot_sequence(")
    warm = seq.split("async def _warm_dashboard_cache():", 1)[1].split("asyncio.create_task", 1)[0]
    assert "CACHE_WARM_DELAY_SECS" in warm, \
        "the catalogue-wide cache warm-up must not spike a freshly started pod"


# ── deployment-gate blockers ─────────────────────────────────────────────────
def test_super_admin_credentials_come_from_the_environment():
    assert 'SUPER_ADMIN_EMAIL = os.environ.get("SUPER_ADMIN_EMAIL", "")' in SRC
    assert 'SUPER_ADMIN_PASSWORD = os.environ.get("SUPER_ADMIN_PASSWORD", "")' in SRC
    # no literal credential left anywhere in the module
    assert os.environ.get("DALEEL_TEST_PASSWORD", "") not in SRC, "the super-admin password must not be in source"
    assert not re.search(r'SUPER_ADMIN_EMAIL\s*=\s*"[^"]*@', SRC), \
        "the super-admin email must not be a literal"
    assert server.SUPER_ADMIN_EMAIL and server.SUPER_ADMIN_PASSWORD, \
        "SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD must be present in backend/.env"


def test_seed_super_admin_refuses_to_run_without_credentials():
    fn = SRC.split("async def seed_super_admin(", 1)[1].split("\nasync def ", 1)[0]
    assert "if not SUPER_ADMIN_EMAIL or not SUPER_ADMIN_PASSWORD:" in fn
    assert "return" in fn.split("SUPER_ADMIN_PASSWORD:", 1)[1][:400]


def test_crawler_token_is_env_only():
    assert 'CRAWLER_TOKEN = os.environ.get("CRAWLER_TOKEN", "")' in SRC
    assert "zj7n4vATDYACt" not in SRC, "the crawler token must not be in source"


def test_debug_token_endpoint_is_gone():
    routes = {getattr(r, "path", None) for r in server.app.router.routes}
    assert "/api/debug/token" not in routes, \
        "an unauthenticated endpoint must never echo a bearer token"


# ── live: the probe target answers immediately ───────────────────────────────
def test_health_endpoint_answers_locally():
    r = requests.get("http://localhost:8001/api/health", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in ("healthy", "degraded")
    assert body["mongodb"] in ("connected", "disconnected")


def test_health_reports_boot_progress():
    """A failed rollout must be diagnosable with one curl."""
    body = requests.get("http://localhost:8001/api/health", timeout=10).json()
    boot = body.get("boot")
    assert isinstance(boot, dict), "/api/health must report the boot state"
    assert boot["status"] in ("pending", "running", "done", "aborted", "mongo_unreachable")
    assert isinstance(boot["errors"], list)
    assert boot["status"] == "done" and not boot["errors"], \
        f"this environment did not finish booting cleanly: {boot}"
