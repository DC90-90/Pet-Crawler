from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


ROOT = Path('/app')
CREDS = ROOT / 'memory/test_credentials.md'


def read_super_password() -> str:
    text = CREDS.read_text()
    m = re.search(r"\*\*Password\*\*:\s*([^\n]+)", text)
    if not m:
        raise RuntimeError('Super admin password not found in test_credentials.md')
    return m.group(1).strip()


def main():
    env = dict(os.environ)
    env['DALEEL_TEST_PASSWORD'] = read_super_password()
    cmd = [
        'pytest',
        '-q',
        '/app/backend/tests/test_iter40_preview_scope_checks.py',
        '--junitxml=/app/test_reports/pytest/iter40_preview_scope_checks.xml',
    ]
    with (ROOT / 'test_reports/same_origin_build_fix/baseline205-attempt-01/test_iter40_preview_scope_checks.log').open('w') as log:
        rc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    raise SystemExit(rc)


if __name__ == '__main__':
    main()
