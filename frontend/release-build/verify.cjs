// Production builds must consume freshly generated, verified export manifests.
// Preview `craco start` is unaffected. A candidate opt-in cannot invent a SHA.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const root = path.resolve(__dirname, '../..');
const sha = data => crypto.createHash('sha256').update(data).digest('hex');
const canonical = value => JSON.stringify(sort(value));
const ignored = new Set(['node_modules', 'build', '__pycache__', '.pytest_cache', '.cache', '.venv', 'venv', 'coverage']);
const generated = new Set(['backend/release_build.json', 'frontend/public/release.json']);
function inventory() {
  const values = {};
  function visit(name) {
    const parts = name.split('/');
    const base = parts[parts.length - 1];
    if (parts.some(p => ignored.has(p)) || base.startsWith('.env') || /\.(pyc|log|pem|key)$/.test(base) || ['credentials.json', 'test_credentials.md'].includes(base) || generated.has(name)) return;
    const full = path.join(root, name);
    if (!fs.existsSync(full)) return;
    const stat = fs.lstatSync(full);
    if (stat.isSymbolicLink()) throw Error('Symlink release input: ' + name);
    if (stat.isDirectory()) fs.readdirSync(full).forEach(child => visit(name + '/' + child));
    else if (stat.isFile()) values[name] = sha(fs.readFileSync(full));
  }
  ['backend', 'frontend', 'scripts', 'deploy', '.github', '.dockerignore', '.gitignore', '.gitattributes', '.emergent/crons.yml'].forEach(visit);
  return values;
}
function sort(value) {
  if (Array.isArray(value)) return value.map(sort);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k, sort(value[k])]));
  return value;
}
function verify() {
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'backend/release_build.json')));
  const front = JSON.parse(fs.readFileSync(path.join(root, 'frontend/public/release.json')));
  const keys = ['schema_version', 'git_commit', 'source_state', 'source_files', 'build_context'];
  const payload = Object.fromEntries(keys.map(k => [k, manifest[k]]));
  if (manifest.schema_version !== 2 || manifest.release_id !== 'sha256:' + sha(canonical(payload))) throw Error('Invalid generated release identity');
  if (canonical(front) !== canonical(manifest)) throw Error('Backend/frontend manifest mismatch');
  if (manifest.source_state !== (manifest.git_commit ? 'committed-export' : 'uncommitted-candidate')) throw Error('Invalid source state');
  if (!manifest.source_files['frontend/yarn.lock'] || manifest.lock_sha256 !== manifest.source_files['frontend/yarn.lock']) throw Error('Invalid lock hash');
  const backend = Object.fromEntries(Object.entries(manifest.source_files).filter(([k]) => k.startsWith('backend/')).map(([k,v]) => [k.slice(8), v]));
  if (canonical(backend) !== canonical(manifest.backend_files)) throw Error('Invalid backend inventory');
  if (canonical(inventory()) !== canonical(manifest.source_files)) throw Error('Release input inventory changed, added or removed');
  if (!manifest.git_commit && process.env.DALEEL_ALLOW_CANDIDATE_BUILD !== 'true') throw Error('Saved-source manifest required for production build');
  if (manifest.git_commit && (!/^[0-9a-f]{40}$/.test(manifest.git_commit) || manifest.source_state !== 'committed-export')) throw Error('Invalid saved-source attribution');
  for (const [name, hash] of Object.entries(manifest.source_files)) {
    if (sha(fs.readFileSync(path.join(root, name))) !== hash) throw Error(`Release input changed: ${name}`);
  }
  for (const [key, value] of Object.entries(manifest.build_context)) {
    if (process.env[key] !== value) throw Error(`Build context mismatch: ${key}`);
  }
  const unexpected = Object.keys(process.env).filter(k => k.startsWith('REACT_APP_') && !(k in manifest.build_context));
  if (unexpected.length) throw Error('Unrecorded public build environment: ' + unexpected.join(','));
  return manifest;
}
module.exports = { verify };
if (require.main === module) console.log(verify().release_id);