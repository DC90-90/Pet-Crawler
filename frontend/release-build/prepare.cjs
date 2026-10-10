// Standard managed builds can compile without Git/backend/exporter access.
// Prepared exact-source artifacts retain the original strict validation path.
const fs = require('fs');
const path = require('path');
const { makeReceipt } = require('./receipt.cjs');
const { BuildReceiptPlugin } = require('./build-plugin.cjs');
const frontend = path.resolve(__dirname, '..');

function prepareBuild() {
  const requirement = process.env.DALEEL_REQUIRE_VERIFIED_RELEASE_BUILD;
  if (requirement !== undefined && !['true', 'false'].includes(requirement)) {
    throw Error('DALEEL_REQUIRE_VERIFIED_RELEASE_BUILD must be true or false');
  }
  const backendManifest = fs.existsSync(path.join(frontend, '../backend/release_build.json'));
  const frontendManifest = fs.existsSync(path.join(frontend, 'public/release.json'));
  const strict = requirement === 'true' || backendManifest || frontendManifest;
  if (strict && (!backendManifest || !frontendManifest)) {
    throw Error('Strict release build requires both generated manifests; refusing unverified fallback');
  }
  const read = () => {
    const manifest = strict ? require('./verify.cjs').verify() : null;
    return makeReceipt(frontend, process.env, manifest);
  };
  const receipt = read();
  if (!strict) {
    console.warn('[release-build] Managed frontend build: source SHA and paired release identity are UNVERIFIED. Readiness/write safeguards are unchanged.');
  }
  return { receipt, plugin: new BuildReceiptPlugin(receipt, read) };
}
module.exports = { prepareBuild };