"""Shared safety guard for legacy regression fixtures selected for this review."""
import os
import uuid
from urllib.parse import urlsplit
from pymongo import MongoClient


def mongo_url():
    url = os.environ["DALEEL_TEST_MONGO_URL"]
    if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Reviewed tests require loopback MongoDB")
    return url


def database_name(label):
    return f"test_reviewed_{label}_{uuid.uuid4().hex}"


def drop_database(name):
    if not name.startswith("test_reviewed_"):
        raise RuntimeError("Refusing to drop a non-test database")
    with MongoClient(mongo_url()) as client:
        client.drop_database(name)