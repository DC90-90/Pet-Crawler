"""Start a headless browser that actually runs (27 Oct 2026).

Production's default Chromium crashed at launch on every crawl
("Target page, context or browser has been closed" from
/pw-browsers/chromium_headless_shell-1208/chrome-headless-shell-linux64/...):
Salla barcodes read from the rendered page failed for every product (Zarafa
642/643, Lana 528/528, CutePets 741/741) and Catshoop could not be crawled.
The workspace's /pw-browsers/.../chrome-linux/headless_shell starts fine.
launch() tries the default, then every Chromium build found on disk, keeps
the first that starts for this process, and check() reports each attempt.
"""
import glob
import logging
import os

log = logging.getLogger(__name__)
_working = {"path": None}       # "" = the default works; a path = that build works

_PATTERNS = (
    "chromium_headless_shell-*/chrome-linux/headless_shell",
    "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
    "chromium-*/chrome-linux/chrome",
    "chromium-*/chrome-linux64/chrome",
)


def candidates():
    roots = [r for r in (os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), "/pw-browsers",
                         os.path.expanduser("~/.cache/ms-playwright")) if r]
    found = []
    for root in dict.fromkeys(roots):
        for pat in _PATTERNS:
            for p in sorted(glob.glob(os.path.join(root, pat)), reverse=True):
                if os.path.isfile(p) and os.access(p, os.X_OK) and p not in found:
                    found.append(p)
    return found


async def launch(pw, **kwargs):
    """pw.chromium.launch(**kwargs), falling back to any Chromium on disk."""
    if _working["path"]:
        return await pw.chromium.launch(executable_path=_working["path"], **kwargs)
    if _working["path"] == "":
        return await pw.chromium.launch(**kwargs)
    try:
        browser = await pw.chromium.launch(**kwargs)
        _working["path"] = ""
        return browser
    except Exception as exc:  # noqa: BLE001 — try the builds on disk
        first = exc
        log.warning("[Browser] default launch failed: %s", str(exc)[:300])
    for path in candidates():
        try:
            browser = await pw.chromium.launch(executable_path=path, **kwargs)
            _working["path"] = path
            log.info("[Browser] using %s", path)
            return browser
        except Exception as exc:  # noqa: BLE001
            log.warning("[Browser] %s failed: %s", path, str(exc)[:200])
    raise first


def missing_libs(path):
    """System libraries a browser binary needs and the server lacks (ldd)."""
    import subprocess
    try:
        out = subprocess.run(["ldd", path], capture_output=True, text=True, timeout=30).stdout
    except Exception as exc:  # noqa: BLE001
        return [f"ldd unavailable: {type(exc).__name__}"]
    return sorted({line.split("=>")[0].strip() for line in out.splitlines() if "not found" in line})


def _tail(text, n=1200):
    """The end of a launch error: the reason follows a very long command line."""
    text = str(text)
    head = text.splitlines()[0] if text else ""
    return head if len(text) <= n else head + " … " + text[-n:]


def repair():
    """Install the system libraries Chromium needs (playwright install-deps,
    root + apt). Blocking; run it in a thread."""
    import subprocess
    import sys
    cmd = [sys.executable, "-m", "playwright", "install-deps", "chromium"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        result = {"cmd": " ".join(cmd), "returncode": r.returncode, "stdout": r.stdout[-2000:], "stderr": r.stderr[-2000:]}
    except Exception as exc:  # noqa: BLE001
        result = {"cmd": " ".join(cmd), "returncode": None, "error": f"{type(exc).__name__}: {exc}"}
    _working["path"] = None          # try the default again
    return result


async def check():
    """Every launch attempt with its outcome, for the admin."""
    import asyncio
    from playwright.async_api import async_playwright
    shm = None
    try:
        st = os.statvfs("/dev/shm")
        shm = round(st.f_bavail * st.f_frsize / 1048576)
    except Exception:  # noqa: BLE001
        pass
    out = {"env_PLAYWRIGHT_BROWSERS_PATH": os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), "attempts": [],
           "uid": getattr(os, "getuid", lambda: None)(), "dev_shm_free_mb": shm}
    async with async_playwright() as pw:
        out["default_executable"] = pw.chromium.executable_path
        for path in [None] + candidates():
            try:
                browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"],
                                                   **({"executable_path": path} if path else {}))
                page = await browser.new_page()
                await page.goto("about:blank")
                await browser.close()
                out["attempts"].append({"path": path or "default", "ok": True})
            except Exception as exc:  # noqa: BLE001
                out["attempts"].append({"path": path or "default", "ok": False, "error": _tail(exc),
                                        "missing_libs": await asyncio.to_thread(missing_libs, path or pw.chromium.executable_path)})
    out["working_in_this_process"] = _working["path"]
    return out
