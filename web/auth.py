"""Session cookies, Telegram login codes, CSRF, login rate limits."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass

CODE_TTL = 600          # 10 minutes
SESSION_TTL = 7 * 86400  # 7 days
MAX_ATTEMPTS = 8
ATTEMPT_WINDOW = 600


@dataclass
class AuthState:
    secret: bytes
    password: str
    admin_ids: set[int]
    codes: dict[int, tuple[str, float]]          # admin_id -> (code, expires)
    attempts: dict[str, list[float]]             # ip -> timestamps
    lock: threading.Lock


def make_auth(secret: str, password: str, admin_ids: set[int], bot_token: str = "") -> AuthState:
    raw = (secret or bot_token or secrets.token_hex(32)).encode()
    return AuthState(secret=hashlib.sha256(raw + b"|kdrama-web").digest(),
                     password=password or "", admin_ids=set(admin_ids),
                     codes={}, attempts={}, lock=threading.Lock())


def _sign(auth: AuthState, payload: str) -> str:
    return hmac.new(auth.secret, payload.encode(), hashlib.sha256).hexdigest()


def issue_session(auth: AuthState, admin_id: int) -> str:
    exp = int(time.time()) + SESSION_TTL
    payload = f"{admin_id}:{exp}"
    return f"{payload}:{_sign(auth, payload)}"


def read_session(auth: AuthState, cookie: str | None) -> int | None:
    if not cookie:
        return None
    try:
        admin_s, exp_s, sig = cookie.split(":", 2)
        payload = f"{admin_s}:{exp_s}"
        if not hmac.compare_digest(sig, _sign(auth, payload)):
            return None
        if int(exp_s) < time.time():
            return None
        admin_id = int(admin_s)
        if admin_id not in auth.admin_ids:
            return None
        return admin_id
    except (ValueError, TypeError):
        return None


def csrf_token(auth: AuthState, admin_id: int) -> str:
    # stable for the session day-ish but bound to admin + secret
    day = int(time.time()) // 86400
    return _sign(auth, f"csrf:{admin_id}:{day}")[:32]


def check_csrf(auth: AuthState, admin_id: int, token: str | None) -> bool:
    if not token:
        return False
    return hmac.compare_digest(token, csrf_token(auth, admin_id))


def rate_limited(auth: AuthState, ip: str) -> bool:
    now = time.time()
    with auth.lock:
        hits = [t for t in auth.attempts.get(ip, []) if now - t < ATTEMPT_WINDOW]
        auth.attempts[ip] = hits
        return len(hits) >= MAX_ATTEMPTS


def record_attempt(auth: AuthState, ip: str) -> None:
    with auth.lock:
        auth.attempts.setdefault(ip, []).append(time.time())


def issue_code(auth: AuthState, admin_id: int) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    with auth.lock:
        auth.codes[admin_id] = (code, time.time() + CODE_TTL)
    return code


def verify_code(auth: AuthState, admin_id: int, code: str) -> bool:
    with auth.lock:
        row = auth.codes.get(admin_id)
        if not row:
            return False
        expect, exp = row
        if time.time() > exp:
            auth.codes.pop(admin_id, None)
            return False
        ok = hmac.compare_digest(expect, (code or "").strip())
        if ok:
            auth.codes.pop(admin_id, None)
        return ok


def verify_password(auth: AuthState, password: str) -> bool:
    if not auth.password:
        return False
    return hmac.compare_digest(auth.password, password or "")
