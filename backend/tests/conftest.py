"""Suite-wide setup: make `_auth` importable and resolve the preview URL once."""
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

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
