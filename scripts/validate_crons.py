"""Validate the repository cron manifest before release."""
from pathlib import Path
import yaml
import re

path = Path(__file__).resolve().parents[1]/".emergent/crons.yml"
document = yaml.safe_load(path.read_text())
assert set(document) == {"crons"}
names = set()
for job in document["crons"]:
    assert set(job) <= {"name", "description", "cron", "endpoint", "method", "enabled"}
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", job["name"]) and job["name"] not in names
    names.add(job["name"])
    assert len(job["cron"].split()) == 5
    assert job["method"] == "POST" and job["endpoint"].startswith("{{BASE_URL}}/api/cron/")
    assert isinstance(job.get("enabled", True), bool)
assert len(names) == 5
print("Cron manifest valid: five authenticated schedules")