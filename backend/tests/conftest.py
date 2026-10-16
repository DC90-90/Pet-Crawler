"""Suite-wide setup: make `_auth` importable and resolve the preview URL once."""
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# backend/ too, so a suite can import the module it is testing (matcher, market_share, …)
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
# Fixtures seed v2 observations dated weeks or months back; the production
# cut-over bound (observation_contract.v2_since) must not hide them.
os.environ.setdefault("OBSERVATIONS_V2_SINCE", "2000-01-01T00:00:00+00:00")
# Fixtures seed interval facts; production reads ledger sales (ledger_sales.py),
# which has its own tests.
os.environ.setdefault("SALES_SOURCE", "v2")

# Several modules read REACT_APP_BACKEND_URL at import time (some with a stale
# hardcoded fallback). Resolve it from frontend/.env before collection starts.
if not os.environ.get("REACT_APP_BACKEND_URL", "").strip():
    dotenv = _HERE.parents[1] / "frontend" / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                val = line.split("=", 1)[1].strip().rstrip("/")
                if val:
                    os.environ["REACT_APP_BACKEND_URL"] = val
                break


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_cohort_memo():
    """The cohort memo is keyed on the observation revision, which production
    writes bump; fixtures that insert snapshots directly do not, so each test
    starts from an empty memo (16 Oct 2026: the memo key now repeats)."""
    try:
        import price_cohort
        price_cohort.reset_cohort_memo()
    except Exception:  # noqa: BLE001 — a suite that cannot import it does not use it
        pass
    yield
