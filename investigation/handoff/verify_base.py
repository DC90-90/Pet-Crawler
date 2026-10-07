import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
manifest=json.loads(Path(__file__).with_name('base-manifest.json').read_text())
errors=[]
for entry in manifest['files']:
    p=root/entry['path']; expected=entry['base_sha256']
    actual=hashlib.sha256(p.read_text(encoding='utf-8').encode('utf-8')).hexdigest() if p.exists() else None
    if actual!=expected: errors.append(entry['path'])
if errors:
    raise SystemExit('Base mismatch; do not apply: '+', '.join(errors))
print('All affected source files match the expected base.')
