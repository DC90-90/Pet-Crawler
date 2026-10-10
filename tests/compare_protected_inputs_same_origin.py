from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path('/app')
BEFORE = ROOT / 'test_reports/same_origin_build_fix/protected-inputs-before.json'
OUT = ROOT / 'test_reports/same_origin_build_fix/protected-inputs-compare-attempt01.json'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    before = json.loads(BEFORE.read_text())
    after = {}
    compare = {}
    for rel, old_hash in before.items():
        path = ROOT / rel
        if path.exists():
            new_hash = sha(path)
            after[rel] = new_hash
            compare[rel] = {'before': old_hash, 'after': new_hash, 'unchanged': old_hash == new_hash}
        else:
            compare[rel] = {'before': old_hash, 'after': None, 'unchanged': False}
    report = {
        'all_unchanged': all(v['unchanged'] for v in compare.values()),
        'comparison': compare,
    }
    OUT.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'all_unchanged': report['all_unchanged'], 'output': str(OUT)}))


if __name__ == '__main__':
    main()
