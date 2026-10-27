"""A crashing default browser falls back to a Chromium build on disk (27 Oct
2026: production's default headless shell crashed on every crawl)."""
import asyncio
import os
import stat
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import browser_launch  # noqa: E402


class FakeChromium:
    def __init__(self, good):
        self.good, self.calls = good, []

    async def launch(self, executable_path=None, **kwargs):
        self.calls.append(executable_path)
        if (os.path.normpath(executable_path) if executable_path else executable_path) == self.good:
            return "browser:" + str(executable_path)
        raise RuntimeError("Target page, context or browser has been closed")


class FakePW:
    def __init__(self, good):
        self.chromium = FakeChromium(good)


def make_exe(root, rel):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return os.path.normpath(path)


def test_falls_back_to_a_build_on_disk_and_remembers_it(tmp_path, monkeypatch):
    root = str(tmp_path)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", root)
    crashing = make_exe(root, "chromium_headless_shell-1208/chrome-headless-shell-linux64/chrome-headless-shell")
    working = make_exe(root, "chromium_headless_shell-1208/chrome-linux/headless_shell")
    found = [os.path.normpath(p) for p in browser_launch.candidates()]
    assert working in found and crashing in found
    browser_launch._working["path"] = None
    pw = FakePW(good=working)
    assert os.path.normpath(asyncio.run(browser_launch.launch(pw, headless=True))[8:]) == working
    assert pw.chromium.calls[0] is None                              # the default is tried first
    pw2 = FakePW(good=working)
    asyncio.run(browser_launch.launch(pw2, headless=True))
    assert [os.path.normpath(c) for c in pw2.chromium.calls] == [working]   # remembered for this process
    browser_launch._working["path"] = None


def test_the_default_is_kept_when_it_works(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    browser_launch._working["path"] = None
    pw = FakePW(good=None)
    assert asyncio.run(browser_launch.launch(pw)) == "browser:None"
    assert browser_launch._working["path"] == ""
    browser_launch._working["path"] = None


def test_the_first_error_is_raised_when_nothing_starts(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    browser_launch._working["path"] = None
    try:
        asyncio.run(browser_launch.launch(FakePW(good="nowhere")))
        raise AssertionError("expected a failure")
    except RuntimeError as exc:
        assert "has been closed" in str(exc)
    assert browser_launch._working["path"] is None
