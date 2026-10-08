"""Remove two historical tracked credential literals without printing or rotating them.

Check-only by default. This reconciles the reviewed package's missed fixture
references; it never edits .env, accounts, Git history, or a database.
"""
import argparse
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
test = root / "backend/tests/test_refactor_regression.py"
original = test.read_text()
updated = re.sub(r'^CRAWLER_TOKEN\s*=\s*["\'][^"\'\n]*["\']\s*$',
                 'CRAWLER_TOKEN = os.environ.get("DALEEL_TEST_CRAWLER_TOKEN", "")', original, flags=re.M)
report = root / "test_reports/iteration_13.json"
content = json.loads(report.read_text())
credentials = content.get("test_credentials", {})
for field in ("admin_password", "crawler_token"):
    if field in credentials:
        credentials[field] = "[REDACTED — use isolated test environment]"
changes = [(test, updated), (report, json.dumps(content, ensure_ascii=False, indent=2) + "\n")]
for path, text in changes:
    if path.read_text() != text:
        print(("Sanitizing " if args.apply else "Needs sanitization: ") + str(path.relative_to(root)))
        if args.apply:
            path.write_text(text)