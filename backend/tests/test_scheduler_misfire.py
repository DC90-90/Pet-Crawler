"""Scheduled crawls survive a busy event loop: a late trigger still runs
(misfire grace one hour), missed runs coalesce (13 Oct 2026)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_scheduler_job_defaults_tolerate_a_busy_loop():
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
    os.environ.setdefault("DB_NAME", "test_scheduler_misfire")
    os.environ.setdefault("JWT_SECRET", "x" * 32)
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
    from cryptography.fernet import Fernet
    os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
    import server
    defaults = server.scheduler._job_defaults
    assert defaults["misfire_grace_time"] >= 3600
    assert defaults["coalesce"] is True
    assert defaults["max_instances"] == 1
