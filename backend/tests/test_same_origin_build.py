"""Same-origin build regressions: receipt/apiOrigin, plugin checks, and API resolver behavior."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _run_node(cwd: Path, script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    runner = cwd / "node_runner.cjs"
    runner.write_text(script)
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(["node", str(runner)], cwd=cwd, env=merged, text=True, capture_output=True)


def _seed_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    files = {
        "frontend/release-build/receipt.cjs": (ROOT / "frontend/release-build/receipt.cjs").read_text(),
        "frontend/release-build/build-plugin.cjs": (ROOT / "frontend/release-build/build-plugin.cjs").read_text(),
        "frontend/src/lib/api.js": (ROOT / "frontend/src/lib/api.js").read_text(),
        "frontend/yarn.lock": "left-pad@1.3.0:\n  version \"1.3.0\"\n",
        "frontend/package.json": "{\"name\":\"fixture\",\"version\":\"1.0.0\",\"private\":true}",
        "frontend/craco.config.js": "module.exports = {};\n",
        "frontend/src/index.js": "console.log('fixture');\n",
        "frontend/public/index.html": "<html><body>fixture</body></html>\n",
    }
    for rel, content in files.items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return ws


# modules/features: receipt.cjs apiOrigin + makeReceipt same-origin/null + explicit origin rules
@pytest.mark.parametrize("value", [None, "", "   \t  "])
def test_receipt_api_origin_empty_unset_whitespace_map_to_null(value: str | None, tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    payload = "undefined" if value is None else json.dumps(value)
    script = f"""
const {{ apiOrigin }} = require('./frontend/release-build/receipt.cjs');
const env = {{}};
if ({payload} !== undefined) env.REACT_APP_BACKEND_URL = {payload};
console.log(JSON.stringify(apiOrigin(env)));
"""
    result = _run_node(ws, script)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "null"


@pytest.mark.parametrize("value", [None, "", "  "])
def test_make_receipt_sets_same_origin_mode_and_null_provenance_without_manifest(value: str | None, tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    payload = "undefined" if value is None else json.dumps(value)
    script = f"""
const {{ makeReceipt }} = require('./frontend/release-build/receipt.cjs');
const env = {{ NODE_ENV: 'production' }};
if ({payload} !== undefined) env.REACT_APP_BACKEND_URL = {payload};
const receipt = makeReceipt('./frontend', env, null);
console.log(JSON.stringify(receipt));
"""
    result = _run_node(ws, script)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout.strip().splitlines()[-1])
    assert receipt["receipt_schema"] == 2
    assert receipt["api_mode"] == "same-origin"
    assert receipt["api_origin"] is None
    assert receipt["source_state"] == "unverified-managed-workspace"
    assert receipt["git_commit"] is None
    assert receipt["release_id"] is None
    assert receipt["manifest_verified"] is False


def test_receipt_api_origin_accepts_explicit_valid_http_https(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    script = """
const { apiOrigin } = require('./frontend/release-build/receipt.cjs');
const values = ['https://example.com', 'http://preview.example.test:8080'];
console.log(JSON.stringify(values.map(v => apiOrigin({ REACT_APP_BACKEND_URL: v }))));
"""
    result = _run_node(ws, script)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == [
        "https://example.com",
        "http://preview.example.test:8080",
    ]


@pytest.mark.parametrize(
    "value",
    [
        "example.com",
        "//example.com",
        "/api",
        "ftp://example.com",
        "https://example.com/path",
        "https://example.com?x=1",
        "https://example.com#frag",
        "https://user:pass@example.com",
    ],
)
def test_receipt_api_origin_rejects_invalid_string_forms(value: str, tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    script = f"""
const {{ apiOrigin }} = require('./frontend/release-build/receipt.cjs');
try {{
  apiOrigin({{ REACT_APP_BACKEND_URL: {json.dumps(value)} }});
  console.log('NO_ERROR');
}} catch (e) {{
  console.error(e.message);
  process.exit(2);
}}
"""
    result = _run_node(ws, script)
    assert result.returncode != 0
    assert "REACT_APP_BACKEND_URL must be" in result.stderr


@pytest.mark.parametrize("js_expr", ["42", "true", "null", "({a:1})", "['x']"])
def test_receipt_api_origin_rejects_non_string_values(js_expr: str, tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    script = f"""
const {{ apiOrigin }} = require('./frontend/release-build/receipt.cjs');
try {{
  apiOrigin({{ REACT_APP_BACKEND_URL: {js_expr} }});
  console.log('NO_ERROR');
}} catch (e) {{
  console.error(e.message);
  process.exit(2);
}}
"""
    result = _run_node(ws, script)
    assert result.returncode != 0
    assert "REACT_APP_BACKEND_URL must be" in result.stderr


def _plugin_script(definition_values: list[str | None], receipt_origin: str | None, mutate: bool = False) -> str:
    defs = []
    for v in definition_values:
        if v is None:
            defs.append("{ definitions: { 'process.env': { OTHER_KEY: '1' } } }")
        else:
            defs.append(
                "{ definitions: { 'process.env': { REACT_APP_BACKEND_URL: "
                + json.dumps(json.dumps(v))
                + " } } }"
            )
    receipt = json.dumps({"api_origin": receipt_origin, "marker": 1})
    revalidate = json.dumps({"api_origin": receipt_origin, "marker": 2 if mutate else 1})
    return f"""
const {{ BuildReceiptPlugin }} = require('./frontend/release-build/build-plugin.cjs');
const receipt = {receipt};
const plugin = new BuildReceiptPlugin(receipt, () => ({revalidate}));
let processAssets;
const emitted = {{}};
const compiler = {{
  webpack: {{ Compilation: {{ PROCESS_ASSETS_STAGE_REPORT: 1 }}, sources: {{ RawSource: class {{ constructor(v){{ this.value=v; }} }} }} }},
  options: {{ plugins: [{', '.join(defs)}] }},
  hooks: {{ thisCompilation: {{ tap: (_n, cb) => cb({{ hooks: {{ processAssets: {{ tap: (_o, fn) => {{ processAssets = fn; }} }} }}, emitAsset: (name, src) => {{ emitted[name] = src.value; }} }}) }} }}
}};
plugin.apply(compiler);
try {{
  processAssets();
  console.log(JSON.stringify({{ ok: true, assets: Object.keys(emitted) }}));
}} catch (e) {{
  console.error(e.message);
  process.exit(2);
}}
"""


# modules/features: BuildReceiptPlugin compiled-origin consistency and mutation guard
def test_plugin_accepts_missing_define_key_with_null_receipt(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    result = _run_node(ws, _plugin_script([None], None))
    assert result.returncode == 0, result.stderr
    assert "build-provenance.json" in json.loads(result.stdout.strip().splitlines()[-1])["assets"]


@pytest.mark.parametrize("baked", ["", "   "])
def test_plugin_accepts_empty_or_whitespace_baked_key_with_null_receipt(baked: str, tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    result = _run_node(ws, _plugin_script([baked], None))
    assert result.returncode == 0, result.stderr


def test_plugin_rejects_explicit_baked_origin_when_receipt_same_origin(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    result = _run_node(ws, _plugin_script(["https://preview.example.test"], None))
    assert result.returncode != 0
    assert "Compiled API origin differs from frontend build receipt" in result.stderr


@pytest.mark.parametrize("definitions", [[None], [""]])
def test_plugin_rejects_missing_or_empty_baked_key_when_receipt_explicit(definitions: list[str | None], tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    result = _run_node(ws, _plugin_script(definitions, "https://preview.example.test"))
    assert result.returncode != 0
    assert "Compiled API origin differs from frontend build receipt" in result.stderr


def test_plugin_rejects_duplicate_conflicting_definitions(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    result = _run_node(
        ws,
        _plugin_script(
            ["https://preview.example.test", "https://other.example.test"],
            "https://preview.example.test",
        ),
    )
    assert result.returncode != 0
    assert "Compiled API origin differs from frontend build receipt" in result.stderr


def test_plugin_accepts_matching_explicit_case(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    result = _run_node(ws, _plugin_script(["https://preview.example.test"], "https://preview.example.test"))
    assert result.returncode == 0, result.stderr


def test_plugin_rejects_receipt_mutation_during_compilation(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    result = _run_node(ws, _plugin_script(["https://preview.example.test"], "https://preview.example.test", mutate=True))
    assert result.returncode != 0
    assert "Frontend inputs changed during compilation" in result.stderr


def _resolve_api_base(ws: Path, env_value: str | None, browser_origin: str | None, with_window: bool = True) -> str:
    env_json = "{}" if env_value is None else json.dumps({"REACT_APP_BACKEND_URL": env_value})
    window_snippet = "" if not with_window else f"window: {{ location: {{ origin: {json.dumps(browser_origin)} }} }},"
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./frontend/src/lib/api.js', 'utf8');
const start = source.indexOf('function resolveApiBase()');
const end = source.indexOf("\\n\\nexport const API_BASE");
if (start < 0 || end < 0) throw new Error('resolveApiBase not found');
const code = source.slice(start, end) + "\\nresult = resolveApiBase();";
const sandbox = {{
  process: {{ env: {env_json} }},
  URL,
  {window_snippet}
  result: null,
}};
vm.runInNewContext(code, sandbox);
console.log(sandbox.result);
"""
    result = _run_node(ws, script)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


# modules/features: frontend/src/lib/api.js resolveApiBase same-origin fallback contract
def test_api_resolver_empty_or_unset_uses_browser_origin_api(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    assert _resolve_api_base(ws, None, "https://current.example.test") == "https://current.example.test/api"
    assert _resolve_api_base(ws, "", "https://current.example.test") == "https://current.example.test/api"


def test_api_resolver_server_side_without_window_returns_relative_api(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    assert _resolve_api_base(ws, None, None, with_window=False) == "/api"


def test_api_resolver_matching_explicit_origin_returns_configured_origin(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    assert _resolve_api_base(ws, "https://current.example.test", "https://current.example.test") == "https://current.example.test/api"


def test_api_resolver_mismatched_explicit_origin_falls_back_to_browser_origin(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    assert _resolve_api_base(ws, "https://other.example.test", "https://current.example.test") == "https://current.example.test/api"
