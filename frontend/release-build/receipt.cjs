// A frontend receipt describes build inputs; it does NOT attest a saved release.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const ignored = new Set(['node_modules', 'build', '.git', '.cache', 'coverage', '__pycache__']);
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const canonical = value => JSON.stringify(sort(value));
function sort(value) {
  if (Array.isArray(value)) return value.map(sort);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k, sort(value[k])]));
  return value;
}
function apiOrigin(env) {
  const value = env.REACT_APP_BACKEND_URL;
  let url;
  try { url = new URL(value); } catch (_) { throw Error('REACT_APP_BACKEND_URL must be an explicit HTTP(S) origin'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/' || value.trim() !== value) {
    throw Error('REACT_APP_BACKEND_URL must be an origin without credentials/path/query');
  }
  return value;
}
function frontendFiles(frontend) {
  const files = {};
  function visit(relative) {
    const full = path.join(frontend, relative);
    for (const name of fs.readdirSync(full).sort()) {
      if (ignored.has(name) || name.startsWith('.env') || /\.(log|pyc|pem|key)$/.test(name) || name === 'credentials.json') continue;
      const rel = path.posix.join(relative, name);
      if (rel === 'public/release.json') continue;
      const stat = fs.lstatSync(path.join(frontend, rel));
      if (stat.isSymbolicLink()) throw Error('Symlink frontend input: ' + rel);
      if (stat.isDirectory()) visit(rel);
      else if (stat.isFile()) files[rel] = sha(fs.readFileSync(path.join(frontend, rel)));
    }
  }
  visit('');
  for (const name of ['yarn.lock', 'package.json', 'craco.config.js']) {
    if (!files[name]) throw Error('Missing required frontend input: ' + name);
  }
  return files;
}
function makeReceipt(frontend, env, manifest = null) {
  const files = frontendFiles(frontend);
  // Do not expose arbitrary environment values in the public artifact.
  const publicEnv = Object.fromEntries(Object.entries(env).filter(([k]) => k.startsWith('REACT_APP_')));
  const inputs = { frontend_files: files, public_environment_sha256: sha(canonical(publicEnv)),
    build_flags: Object.fromEntries(['NODE_ENV', 'PUBLIC_URL', 'GENERATE_SOURCEMAP', 'ENABLE_HEALTH_CHECK'].map(k => [k, env[k] ?? null])) };
  return { receipt_schema: 1, kind: 'frontend-build-receipt', scope: 'frontend-only',
    source_state: manifest ? manifest.source_state : 'unverified-managed-workspace',
    git_commit: manifest ? manifest.git_commit : null, release_id: manifest ? manifest.release_id : null,
    manifest_verified: Boolean(manifest), production_readiness_verified: false,
    api_origin: apiOrigin(env), lock_sha256: files['yarn.lock'], node_version: process.version,
    frontend_content_sha256: sha(canonical(inputs)), ...inputs };
}
module.exports = { apiOrigin, frontendFiles, makeReceipt, canonical };