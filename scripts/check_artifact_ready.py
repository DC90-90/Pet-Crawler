"""Actual exported FastAPI /api/ready over ASGI, disposable loopback Mongo only.

No mocked application identity or boot, no HTTP listening socket, no production.
Candidate must return503; a verified saved-source export must return200. Neither
result is a production gate signoff or image/runtime dependency certification.
"""
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def check():
    url = os.environ["MONGO_URL"]
    if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Artifact readiness test refuses non-loopback database")
    db_name = "test_packaging_ready_" + uuid.uuid4().hex
    os.environ["DB_NAME"] = db_name
    os.environ["SEED_DEMO_DATA"] = "false"
    import httpx
    import server
    import release_identity
    try:
        before = await server.client[db_name].list_collection_names()
        assert before == []
        await server.app.router.startup()
        for _ in range(100):
            if server.BOOT_STATE["status"] in {"done", "aborted", "mongo_unreachable"}:
                break
            await asyncio.sleep(0.05)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url=os.environ["REACT_APP_BACKEND_URL"]) as client:
            response = await client.get("/api/ready")
            state = await client.get("/api/release")
        identity = release_identity.identity()
        expected = 200 if identity["git_commit"] else 503
        assert response.status_code == expected, response.text
        assert identity["manifest_verified"] is True
        assert response.json()["ready"] is (expected == 200)
        assert server.BOOT_STATE["status"] == "done", server.BOOT_STATE
        assert not any(state.json()["capabilities"].values())
        assert await server.client[db_name].list_collection_names() == []
        return {"http_status": response.status_code, "expected_status": expected, "identity": identity,
                "boot_status": server.BOOT_STATE["status"], "database_collections_created": 0,
                "transport": "actual-exported-app-ASGI", "mocked": False, "all_capabilities_off": True}
    finally:
        await server.client.drop_database(db_name)
        server.client.close()


if __name__ == "__main__":
    value = asyncio.run(check())
    Path(sys.argv[1]).write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(value))