from __future__ import annotations

import json
from pathlib import Path

import requests
from dotenv import dotenv_values


ROOT = Path('/app')
OUT = ROOT / 'test_reports/same_origin_build_fix/ready_health_check_attempt01.json'


def main():
    origin = (dotenv_values(ROOT / 'frontend/.env').get('REACT_APP_BACKEND_URL') or '').strip().rstrip('/')
    if not origin:
        raise RuntimeError('Missing frontend origin')
    ready = requests.get(f'{origin}/api/ready', timeout=30)
    health = requests.get(f'{origin}/api/health', timeout=30)
    report = {
        'origin': origin,
        'ready_status': ready.status_code,
        'health_status': health.status_code,
        'ready_body': ready.json() if 'application/json' in ready.headers.get('content-type', '') else ready.text,
        'health_body': health.json() if 'application/json' in health.headers.get('content-type', '') else health.text,
    }
    OUT.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'ready_status': ready.status_code, 'health_status': health.status_code, 'output': str(OUT)}))


if __name__ == '__main__':
    main()
