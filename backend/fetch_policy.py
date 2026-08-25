"""iter75 — self-reliant fetch policy. No paid proxy, no silent throttling.

The client dropped Webshare after the lapsed subscription took all five Salla
stores down. Crawling direct from the pod works (verified against every store),
but the proxy used to hide two hard edges:

  1. **RATE LIMITS.** One CutePets crawl produced **277 × HTTP 429**: the
     barcode supplement fired one request per product with zero pacing and no
     backoff, so nearly every detail lookup was throttled. That is 20+ wasted
     minutes AND missing barcodes — and barcodes are what the matching engine
     matches on, so a 429 storm silently degrades data quality.
  2. **BOT FINGERPRINTING.** Some storefronts reject a plain httpx TLS
     handshake regardless of headers.

Every crawl request now goes through `polite_get`:
  * per-host adaptive pacing (a host that pushes back gets more space, a host
    that behaves earns the space back),
  * exponential backoff with jitter, honouring `Retry-After`,
  * browser-shaped headers with a rotating User-Agent,
  * and one final attempt through curl_cffi's Chrome TLS impersonation when a
    host answers with a block status even after the retries.

Nothing here raises: a failed fetch returns the last response (or None) exactly
like the callers' previous `try/except` shapes expected.
"""

import asyncio
import logging
import random
import time
from urllib.parse import urlparse

logger = logging.getLogger("fetch_policy")

try:                                        # optional, but installed by default
    from curl_cffi import requests as _curl_requests
except Exception:                           # pragma: no cover
    _curl_requests = None

# Statuses worth another attempt: throttling, transient edge/origin errors and
# the Cloudflare family. 404/400 are NOT here — they are answers, not failures.
RETRY_STATUSES = {403, 408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523,
                  524, 525, 526, 540}
# Statuses that smell like fingerprint/bot rejection rather than load.
IMPERSONATE_STATUSES = {403, 429, 503, 520, 521, 522, 525, 526, 540}

BASE_DELAY = 0.20          # seconds between requests to the same host
MAX_DELAY = 8.0            # ceiling once a host is angry
DECAY_AFTER_OK = 15        # consecutive OKs before we speed back up
JITTER = 0.35              # ±35% so a crawl never looks metronomic
DEFAULT_ATTEMPTS = 3
# Consecutive per-product failures before a supplement pass gives up. Turns
# "1365 wasted requests" into "30 requests and a recorded reason".
SUPPLEMENT_ABORT_AFTER = 30

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# Saudi shoppers' Accept-Language — also what the storefronts expect.
BROWSER_HEADERS = {
    "Accept-Language": "ar-SA,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

_hosts = {}


def _host(url, host_key=None):
    key = host_key or (urlparse(url).netloc or "unknown")
    return key, _hosts.setdefault(key, {"delay": BASE_DELAY, "next_at": 0.0,
                                        "ok_streak": 0, "throttled": 0,
                                        "requests": 0, "impersonated": 0})


async def _pace(state):
    wait = state["next_at"] - time.monotonic()
    if wait > 0:
        await asyncio.sleep(wait)
    spacing = state["delay"] * (1 + random.uniform(-JITTER, JITTER))
    state["next_at"] = time.monotonic() + max(0.0, spacing)
    state["requests"] += 1


def _penalise(state, resp=None):
    state["ok_streak"] = 0
    state["throttled"] += 1
    state["delay"] = min(MAX_DELAY, max(BASE_DELAY, state["delay"] * 2))
    retry_after = 0.0
    if resp is not None:
        try:
            retry_after = float((getattr(resp, "headers", None) or {}).get("Retry-After") or 0)
        except (AttributeError, TypeError, ValueError):
            retry_after = 0.0
    return min(MAX_DELAY, retry_after) if retry_after > 0 else state["delay"]


def _reward(state):
    state["ok_streak"] += 1
    if state["ok_streak"] >= DECAY_AFTER_OK and state["delay"] > BASE_DELAY:
        state["delay"] = max(BASE_DELAY, state["delay"] * 0.7)
        state["ok_streak"] = 0


class ImpersonatedResponse:
    """httpx-shaped view over a curl_cffi response."""

    def __init__(self, raw):
        self.status_code = raw.status_code
        self.content = raw.content or b""
        self.text = raw.text or ""
        self.headers = dict(getattr(raw, "headers", {}) or {})
        self.impersonated = True

    def json(self):
        import json
        return json.loads(self.text)


async def _impersonate(url, params, headers, state):
    """Last resort: replay the request with Chrome's real TLS fingerprint."""
    if _curl_requests is None:
        return None
    try:
        raw = await asyncio.to_thread(
            _curl_requests.get, url, params=params, headers=headers,
            impersonate="chrome", timeout=30)
    except Exception as exc:
        logger.info("[fetch] impersonation failed for %s: %s", url, str(exc)[:90])
        return None
    state["impersonated"] += 1
    logger.info("[fetch] impersonated %s → HTTP %s", url, raw.status_code)
    return ImpersonatedResponse(raw)


async def polite_get(client, url, params=None, headers=None,
                     attempts=DEFAULT_ATTEMPTS, host_key=None):
    """GET with pacing, backoff, UA rotation and a TLS-impersonation fallback.

    Returns the response (httpx or ImpersonatedResponse) or None when every
    attempt raised. Never raises — callers keep their existing branching on
    `resp.status_code`.
    """
    key, state = _host(url, host_key)
    merged_base = dict(BROWSER_HEADERS)
    if headers:
        merged_base.update(headers)
    last_resp = None
    for attempt in range(max(1, attempts)):
        await _pace(state)
        send_headers = dict(merged_base)
        send_headers.setdefault("User-Agent", random.choice(_UA_POOL))
        if attempt:                     # a retry gets a fresh identity
            send_headers["User-Agent"] = random.choice(_UA_POOL)
        try:
            resp = await client.get(url, params=params, headers=send_headers)
        except Exception as exc:
            _penalise(state)
            logger.info("[fetch] %s attempt %d raised %s: %s",
                        key, attempt + 1, type(exc).__name__, str(exc)[:80])
            last_resp = None
            continue
        if resp.status_code not in RETRY_STATUSES:
            _reward(state)
            return resp
        last_resp = resp
        sleep_for = _penalise(state, resp)
        logger.info("[fetch] %s HTTP %s — backing off %.2fs (delay now %.2fs)",
                    key, resp.status_code, sleep_for, state["delay"])
        if attempt < attempts - 1:
            await asyncio.sleep(sleep_for)

    if last_resp is not None and last_resp.status_code in IMPERSONATE_STATUSES:
        shimmed = await _impersonate(url, params, merged_base, state)
        if shimmed is not None and shimmed.status_code not in RETRY_STATUSES:
            _reward(state)
            return shimmed
        if shimmed is not None:
            return shimmed
    return last_resp


def host_saturated(url, host_key=None):
    """True when a host has pushed us to the maximum delay.

    iter75 — hamtaro.sa 429s its per-product details route even through Chrome
    TLS impersonation (the limit is per IP, not per fingerprint). Once a host has
    us at MAX_DELAY, further per-product requests cost ~24s each and return
    nothing: the caller should stop that stage, not grind through the catalogue.
    """
    key = host_key or (urlparse(url).netloc or "unknown")
    st = _hosts.get(key)
    return bool(st and st["delay"] >= MAX_DELAY)


def host_diagnostics():
    """Per-host pacing snapshot for the admin crawl-health endpoint."""
    return {k: {"delay_secs": round(v["delay"], 2), "requests": v["requests"],
                "throttled": v["throttled"], "impersonated": v["impersonated"]}
            for k, v in sorted(_hosts.items())}


def reset_hosts():
    _hosts.clear()


def impersonation_available():
    return _curl_requests is not None
