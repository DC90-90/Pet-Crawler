"""Zid Partner-app OAuth 2.0 — the credential the Orders API has always needed.

Zid splits its Merchant API across TWO tokens and the orders route needs both:

    Authorization: Bearer  <the OAuth response's `authorization` field>
    X-Manager-Token:       <the OAuth response's `access_token` field>

The store Access-Token we already hold (`ZID_API_TOKEN`) is only the second of
those, which is exactly why `/v1/products/` answers 200 while
`/v1/managers/store/orders` answers 401 "Unauthenticated" (iter75 probed all
five header permutations). The missing half can ONLY be obtained by the store
owner installing/authorising our partner app, so this module implements the
authorization-code flow end to end and persists the resulting pair.

Storage: one document in `zid_oauth` (_id "own"), every token value encrypted
at rest with the same Fernet key the Tier-4 credential vault uses. Tokens are
never returned to the frontend and never logged.
"""

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("zid_oauth")

OAUTH_BASE = "https://oauth.zid.sa"
AUTHORIZE_URL = f"{OAUTH_BASE}/oauth/authorize"
TOKEN_URL = f"{OAUTH_BASE}/oauth/token"

CALLBACK_PATH = "/api/zid/oauth/callback"
DEFAULT_SCOPES = "orders.read"

# Zid issues year-long tokens; refresh well before the edge (its own docs
# recommend ~10 months). We refresh whenever less than this remains.
REFRESH_MARGIN = timedelta(days=30)
STATE_TTL = timedelta(minutes=20)

_DOC_ID = "own"
_SECRET_FIELDS = ("authorization", "access_token", "refresh_token")


def _fernet():
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY is missing — cannot store Zid tokens")
    return Fernet(key.encode())


def _enc(value):
    if not value:
        return None
    return _fernet().encrypt(str(value).encode()).decode()


def _dec(value):
    if not value:
        return None
    try:
        return _fernet().decrypt(str(value).encode()).decode()
    except (InvalidToken, ValueError):
        logger.error("[ZidOAuth] stored token could not be decrypted — re-authorisation required")
        return None


def client_id():
    return (os.environ.get("ZID_CLIENT_ID") or "").strip()


def client_secret():
    return (os.environ.get("ZID_CLIENT_SECRET") or "").strip()


def scopes():
    return (os.environ.get("ZID_OAUTH_SCOPES") or DEFAULT_SCOPES).strip()


def configured():
    return bool(client_id() and client_secret())


def resolve_redirect_uri(base_url=None):
    """The callback Zid must redirect to — it has to match EXACTLY between the
    authorize call, the token exchange and the value registered in the Partner
    dashboard. An explicit env override wins; otherwise it is derived from the
    request's own public base URL so preview and production each work without
    a config change."""
    explicit = (os.environ.get("ZID_REDIRECT_URI") or "").strip()
    if explicit:
        return explicit
    if not base_url:
        return ""
    return f"{str(base_url).rstrip('/')}{CALLBACK_PATH}"


def build_authorize_url(redirect_uri, state):
    return f"{AUTHORIZE_URL}?" + urlencode({
        "client_id": client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes(),
        "state": state,
    })


async def start_authorization(db, base_url=None):
    """Mint a one-time state and return the URL the merchant must open.

    `base_url` is the PUBLIC origin the browser is on. It must be passed by the
    caller (the frontend sends `window.location.origin`) because behind the
    ingress `request.base_url` can resolve to an internal cluster hostname,
    and Zid matches the redirect URI byte-for-byte against what was registered.
    """
    redirect_uri = resolve_redirect_uri(base_url)
    if not configured():
        return {"ok": False, "reason": "not_configured",
                "message": "ZID_CLIENT_ID / ZID_CLIENT_SECRET are not set"}
    if not redirect_uri:
        return {"ok": False, "reason": "no_redirect_uri",
                "message": "Could not resolve a callback URL"}
    state = secrets.token_urlsafe(24)
    await db.zid_oauth_states.insert_one({
        "state": state, "redirect_uri": redirect_uri,
        "created_at": datetime.now(timezone.utc), "used": False,
    })
    return {"ok": True, "authorize_url": build_authorize_url(redirect_uri, state),
            "redirect_uri": redirect_uri, "state": state, "scope": scopes()}


async def _post_token(form):
    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.post(TOKEN_URL, data=form,
                               headers={"Accept": "application/json"})
    if resp.status_code >= 400:
        # Never log the secret, the code or any token value.
        logger.error("[ZidOAuth] token endpoint rejected the request status=%s grant=%s",
                     resp.status_code, form.get("grant_type"))
        return None, {"status": resp.status_code, "body": resp.text[:300]}
    try:
        return resp.json(), None
    except ValueError:
        return None, {"status": resp.status_code, "body": "non-JSON response"}


def _extract_tokens(payload):
    """Zid has shifted payload shapes across versions — read defensively and
    accept a `data` envelope. Returns (authorization, access_token,
    refresh_token, expires_in) with None for anything absent."""
    body = payload or {}
    if isinstance(body.get("data"), dict):
        body = {**body, **body["data"]}
    authorization = body.get("authorization") or body.get("Authorization")
    access_token = body.get("access_token") or body.get("accessToken")
    refresh_token = body.get("refresh_token") or body.get("refreshToken")
    try:
        expires_in = int(body.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0
    return authorization, access_token, refresh_token, expires_in


async def _save(db, authorization, access_token, refresh_token, expires_in, redirect_uri):
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=expires_in) if expires_in > 0 else None
    await db.zid_oauth.update_one({"_id": _DOC_ID}, {"$set": {
        "authorization": _enc(authorization),
        "access_token": _enc(access_token),
        "refresh_token": _enc(refresh_token),
        "expires_at": expires_at,
        "expires_in": expires_in or None,
        "scope": scopes(),
        "redirect_uri": redirect_uri,
        "status": "authorized",
        "updated_at": now,
    }, "$setOnInsert": {"connected_at": now}}, upsert=True)


async def complete_authorization(db, code, state, base_url=None):
    """Exchange the one-time code for the token pair and persist it."""
    if not configured():
        return {"ok": False, "reason": "not_configured"}
    st = await db.zid_oauth_states.find_one({"state": state}) if state else None
    if not st:
        return {"ok": False, "reason": "unknown_state",
                "message": "This authorisation link is not one we issued"}
    if st.get("used"):
        return {"ok": False, "reason": "state_reused",
                "message": "This authorisation link has already been used"}
    created = st.get("created_at")
    if created and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if created and datetime.now(timezone.utc) - created > STATE_TTL:
        return {"ok": False, "reason": "state_expired",
                "message": "The authorisation link expired — start again"}
    await db.zid_oauth_states.update_one({"_id": st["_id"]}, {"$set": {"used": True}})

    redirect_uri = st.get("redirect_uri") or resolve_redirect_uri(base_url)
    payload, err = await _post_token({
        "grant_type": "authorization_code",
        "client_id": client_id(),
        "client_secret": client_secret(),
        "redirect_uri": redirect_uri,
        "code": code,
    })
    if payload is None:
        return {"ok": False, "reason": "exchange_failed", "detail": err}
    authorization, access_token, refresh_token, expires_in = _extract_tokens(payload)
    if not authorization or not access_token:
        return {"ok": False, "reason": "incomplete_response",
                "message": "Zid did not return both an authorization and an access_token",
                "fields": sorted(payload.keys()) if isinstance(payload, dict) else []}
    await _save(db, authorization, access_token, refresh_token, expires_in, redirect_uri)
    logger.info("[ZidOAuth] store authorised (scope=%s, expires_in=%s)", scopes(), expires_in)
    return {"ok": True, "expires_in": expires_in, "scope": scopes()}


async def _refresh(db, doc):
    refresh_token = _dec(doc.get("refresh_token"))
    if not refresh_token:
        return None
    payload, err = await _post_token({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id(),
        "client_secret": client_secret(),
        "redirect_uri": doc.get("redirect_uri") or resolve_redirect_uri(),
    })
    if payload is None:
        await db.zid_oauth.update_one({"_id": _DOC_ID}, {"$set": {
            "status": "refresh_failed", "last_error": err, "updated_at": datetime.now(timezone.utc)}})
        return None
    authorization, access_token, new_refresh, expires_in = _extract_tokens(payload)
    # A refresh response replaces what it returns and keeps what it omits.
    authorization = authorization or _dec(doc.get("authorization"))
    access_token = access_token or _dec(doc.get("access_token"))
    await _save(db, authorization, access_token, new_refresh or refresh_token,
                expires_in, doc.get("redirect_uri") or resolve_redirect_uri())
    logger.info("[ZidOAuth] token refreshed (expires_in=%s)", expires_in)
    return {"authorization": authorization, "access_token": access_token}


async def credentials(db):
    """The header pair for an authenticated Merchant-API call, refreshed when
    it is close to expiry. Returns None when the app has never been authorised
    (callers must degrade to a clear 'needs authorisation' state)."""
    doc = await db.zid_oauth.find_one({"_id": _DOC_ID})
    if not doc:
        return None
    expires_at = doc.get("expires_at")
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at - datetime.now(timezone.utc) < REFRESH_MARGIN:
        refreshed = await _refresh(db, doc)
        if refreshed and refreshed.get("authorization") and refreshed.get("access_token"):
            return refreshed
        # Refresh failed — the existing pair may still work until it doesn't.
    authorization, access_token = _dec(doc.get("authorization")), _dec(doc.get("access_token"))
    if not authorization or not access_token:
        return None
    return {"authorization": authorization, "access_token": access_token}


async def status(db):
    """Connection state for the Settings panel — never includes token values."""
    doc = await db.zid_oauth.find_one({"_id": _DOC_ID})
    orders = await db.own_store_orders.count_documents({})
    latest = None
    if orders:
        row = await db.own_store_orders.find_one(
            {}, {"_id": 0, "created_at": 1}, sort=[("created_at", -1)])
        latest = (row or {}).get("created_at")
    out = {
        "configured": configured(),
        "connected": bool(doc and doc.get("status") == "authorized"),
        "status": (doc or {}).get("status") or "not_connected",
        "scope": (doc or {}).get("scope") or scopes(),
        "connected_at": (doc or {}).get("connected_at"),
        "updated_at": (doc or {}).get("updated_at"),
        "expires_at": (doc or {}).get("expires_at"),
        "has_refresh_token": bool((doc or {}).get("refresh_token")),
        "redirect_uri": (doc or {}).get("redirect_uri") or resolve_redirect_uri(),
        "callback_path": CALLBACK_PATH,
        "store_token_present": bool((os.environ.get("ZID_API_TOKEN") or "").strip()),
        "orders_stored": orders,
        "latest_order_at": latest,
        "last_error": (doc or {}).get("last_error"),
    }
    if not out["configured"]:
        out["action_required"] = ("Add ZID_CLIENT_ID and ZID_CLIENT_SECRET from the "
                                  "Zid Partner dashboard to the backend environment")
    elif not out["connected"]:
        out["action_required"] = ("Register the callback URL in the Zid Partner dashboard, "
                                  "enable the orders.read scope, then press Connect")
    return out


async def disconnect(db):
    await db.zid_oauth.delete_one({"_id": _DOC_ID})
    return {"ok": True}
