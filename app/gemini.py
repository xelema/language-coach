"""Gemini over Antigravity OAuth, ported from poc/antigravity-chat.mjs.

PKCE login on localhost:51121, token refresh, loadCodeAssist project lookup,
streamGenerateContent SSE parsing with thought parts skipped.
Token stored under data/ (gitignored), never sent to the browser.

Provider switch: the site settings (or LC_PROVIDER env) route
generate_turn/has_token to the OpenCode Go backend (app/opencode.py).
gemini is the default.
"""
import base64
import hashlib
import json
import secrets
import time
import uuid
from urllib.parse import urlencode

import httpx

from . import opencode, settings
from .auth import data_dir

# Public client of the Antigravity desktop app, embedded in every binary. Not a personal secret.
CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
CLIENT_SECRET = "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"
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
]
# The redirect URI is registered on Google's side, so the port is fixed.
REDIRECT_URI = "http://localhost:51121/oauth-callback"
PROD_API = "https://cloudcode-pa.googleapis.com/v1internal"
# Prod answers 429 on generation for free-tier accounts, the daily sandbox serves them.
GEN_API = "https://daily-cloudcode-pa.sandbox.googleapis.com/v1internal"
FALLBACK_PROJECT = "rising-fact-p41fc"
# Known-good ids on the Antigravity endpoint: no plain "gemini-3.8-flash"
# (404), the tiered one takes a thinking level instead.
MODELS = ["gemini-3.8-flash-tiered", "gemini-2.5-flash"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Antigravity/1.18.3 Chrome/138.0.7204.235 Electron/37.3.1 Safari/537.36",
    "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "Client-Metadata": json.dumps({"ideType": "ANTIGRAVITY", "platform": "WINDOWS", "pluginType": "GEMINI"}),
}

_token: dict | None = None
_project: str | None = None
_pending_pkce: dict = {}


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _token_file():
    return data_dir() / "antigravity_token.json"


def _load_token() -> dict | None:
    global _token
    if _token is None and _token_file().exists():
        _token = json.loads(_token_file().read_text())
    return _token


def has_token() -> bool:
    if settings.current_provider() == "opencode":
        return opencode.has_token()
    return bool((_load_token() or {}).get("refresh_token"))


def _token_request(params: dict) -> None:
    global _token
    res = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, **params},
    )
    body = res.json()
    if res.status_code != 200:
        raise RuntimeError(f"token endpoint: {body}")
    _token = {**(_load_token() or {}), **body, "expires_at": time.time() * 1000 + body["expires_in"] * 1000}
    _token_file().write_text(json.dumps(_token))


def _access_token() -> str:
    t = _load_token()
    if time.time() * 1000 > t["expires_at"] - 60_000:
        _token_request({"grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
        t = _load_token()
    return t["access_token"]


def login_url() -> str:
    _pending_pkce["verifier"] = secrets.token_urlsafe(32)
    _pending_pkce["state"] = secrets.token_urlsafe(16)
    challenge = _b64url(hashlib.sha256(_pending_pkce["verifier"].encode()).digest())
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": _pending_pkce["state"],
        "access_type": "offline",
        "prompt": "consent",
    })


def complete_login(code: str, state: str) -> None:
    if state != _pending_pkce.get("state"):
        raise ValueError("bad state")
    _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": _pending_pkce["verifier"],
        "redirect_uri": REDIRECT_URI,
    })


def _api(base: str, method: str, body: dict, query: str = "") -> httpx.Response:
    res = httpx.post(
        f"{base}:{method}{query}",
        headers={**HEADERS, "Authorization": f"Bearer {_access_token()}"},
        json=body,
    )
    if res.status_code != 200:
        raise RuntimeError(f"{method} {res.status_code}: {res.text}")
    return res


def _project_id() -> str:
    global _project
    if _project is None:
        body = _api(PROD_API, "loadCodeAssist", {}).json()
        p = body.get("cloudaicompanionProject")
        _project = (p if isinstance(p, str) else (p or {}).get("id")) or FALLBACK_PROJECT
    return _project


def _reset_delay(res: httpx.Response) -> float:
    """429 bodies carry a per-second quota reset, ~0.3-0.7s out. Sub-second wait, then retry."""
    try:
        for d in res.json()["error"]["details"]:
            delay = d.get("metadata", {}).get("quotaResetDelay")
            if delay:
                return min(float(delay.rstrip("s")), 2.0)
    except (ValueError, KeyError):
        pass
    return 0.5


def _stream(payload: dict):
    with httpx.stream(
        "POST",
        f"{GEN_API}:streamGenerateContent?alt=sse",
        headers={**HEADERS, "Authorization": f"Bearer {_access_token()}"},
        json=payload,
        timeout=httpx.Timeout(None, connect=10),
    ) as res:
        if res.status_code != 200:
            raise RuntimeError(f"streamGenerateContent {res.status_code}: {res.read().decode()}", res)
        for line in res.iter_lines():
            if not line.startswith("data:"):
                continue
            yield from json.loads(line[5:]).get("response", {}).get("candidates", [{}])[0].get("content", {}).get("parts", [])


def generate_turn(contents: list[dict], system: str | None = None,
                  tools: list[dict] | None = None, on_text=None) -> list[dict]:
    """One model turn. Calls on_text for each visible text chunk (thought parts
    skipped) and returns the raw parts list verbatim — thoughtSignature included,
    so the turn can be echoed back for function calling or stored for replay."""
    if settings.current_provider() == "opencode":
        return opencode.generate_turn(contents, system=system, tools=tools, on_text=on_text)
    request = {
        "contents": contents,
        # Lowest level the tiered model accepts (MINIMAL is rejected), yields zero thought tokens.
        "generationConfig": {"thinkingConfig": {"thinkingLevel": "low"}},
    }
    if system:
        request["systemInstruction"] = {"parts": [{"text": system}]}
    if tools:
        request["tools"] = [{"functionDeclarations": tools}]
    payload = {
        "project": _project_id(),
        "model": settings.current_model("gemini"),
        "request": request,
        "requestType": "agent",
        "userAgent": "antigravity",
        "requestId": f"agent-{uuid.uuid4()}",
    }
    parts = []
    for attempt in range(3):
        try:
            for part in _stream(payload):
                parts.append(part)
                if part.get("text") and not part.get("thought") and on_text:
                    on_text(part["text"])
            return parts
        except RuntimeError as e:
            res = e.args[1] if len(e.args) > 1 else None
            if res is not None and res.status_code == 429 and not parts:
                time.sleep(_reset_delay(res))
                continue
            raise
    return parts


def stream_reply(contents: list[dict]):
    """Yields the model's visible text chunks (thought parts skipped)."""
    chunks = []
    generate_turn(contents, system="You are a helpful Korean language coach.",
                  on_text=chunks.append)
    yield from chunks
