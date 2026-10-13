"""Password check, signed session cookie, login rate limiting.

Run `python -m app.auth` to hash a password into the LC_PASSWORD_HASH format.
"""
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path

SCRYPT_N, SCRYPT_R, SCRYPT_P = 16384, 8, 1
COOKIE_NAME = "lc_session"
SESSION_TTL = 30 * 24 * 3600
MAX_ATTEMPTS, WINDOW = 5, 300

_attempts: dict[str, list[float]] = {}


def data_dir() -> Path:
    d = Path(os.environ.get("LC_DATA_DIR", "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    b64 = lambda b: base64.b64encode(b).decode()
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(digest)}"


def check_password(password: str) -> bool:
    try:
        _, n, r, p, salt, digest = os.environ["LC_PASSWORD_HASH"].split("$")
        candidate = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p)
        )
        return hmac.compare_digest(candidate, base64.b64decode(digest))
    except (KeyError, ValueError):
        return False


def configured() -> bool:
    """True quand un hash de mot de passe est disponible (environnement ou .env).

    Sans lui, la page de connexion refuse tout le monde : mieux vaut le dire
    explicitement que répondre « mot de passe incorrect » à l'infini.
    """
    return bool((os.environ.get("LC_PASSWORD_HASH") or "").strip())


def _secret() -> bytes:
    env = os.environ.get("LC_SESSION_SECRET")
    if env:
        return env.encode()
    f = data_dir() / "session-secret"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip().encode()


def make_session() -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + SESSION_TTL}).encode()).decode()
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def valid_session(cookie: str | None) -> bool:
    if not cookie or "." not in cookie:
        return False
    payload, sig = cookie.rsplit(".", 1)
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        return json.loads(base64.urlsafe_b64decode(payload))["exp"] > time.time()
    except (ValueError, KeyError):
        return False


def throttled(ip: str) -> bool:
    now = time.time()
    fails = [t for t in _attempts.get(ip, []) if now - t < WINDOW]
    _attempts[ip] = fails
    return len(fails) >= MAX_ATTEMPTS


def record_attempt(ip: str, ok: bool) -> None:
    if ok:
        _attempts.pop(ip, None)
    else:
        _attempts.setdefault(ip, []).append(time.time())


if __name__ == "__main__":
    pw = sys.argv[1] if len(sys.argv) > 1 else getpass.getpass("Password: ")
    print(f"LC_PASSWORD_HASH={make_hash(pw)}")
    print("\nÀ coller dans le fichier .env à côté de run.sh : la ligne "
          "LC_PASSWORD_HASH=... sans le # initial. « ./run.sh hash » fait la même chose.",
          file=sys.stderr)
