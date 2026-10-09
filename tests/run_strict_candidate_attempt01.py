from __future__ import annotations

import os
import subprocess
from pathlib import Path

from dotenv import dotenv_values


ROOT = Path('/app')
OUT = ROOT / 'test_reports/same_origin_build_fix/strict-candidate-attempt-01'


def main() -> int:
    if OUT.exists():
        raise RuntimeError(f'Output already exists: {OUT}')
    benv = dotenv_values(ROOT / 'backend/.env')
    fenv = dotenv_values(ROOT / 'frontend/.env')
    mongo = (benv.get('MONGO_URL') or '').strip()
    origin = (fenv.get('REACT_APP_BACKEND_URL') or '').strip()
    if not mongo or not origin:
        raise RuntimeError('Missing MONGO_URL or REACT_APP_BACKEND_URL from env files')

    env = dict(os.environ)
    env['MONGO_URL'] = mongo
    env['REACT_APP_BACKEND_URL'] = origin

    cmd = [
        'python',
        'scripts/verify_clean_release.py',
        '--candidate',
        '--containers',
        '--output',
        str(OUT),
    ]
    with (ROOT / 'test_reports/same_origin_build_fix/strict-candidate-attempt-01.log').open('w') as log:
        return subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode


if __name__ == '__main__':
    raise SystemExit(main())
