"""Password hashing (PBKDF2-SHA256) and signed session tokens (HMAC-SHA256). Standard library only."""
import hmac
import time
import base64
import hashlib
import secrets

from .config import SECRET_KEY, SESSION_HOURS

ITER = 310_000


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt, ITER)
    return f"pbkdf2_sha256${ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, it, salt, dk = stored.split('$')
        calc = hashlib.pbkdf2_hmac('sha256', pw.encode(), base64.b64decode(salt), int(it))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


def make_token(user_id: int, pw_hash: str) -> str:
    exp = int(time.time()) + SESSION_HOURS * 3600
    # binding a fingerprint of the password hash invalidates sessions when the password changes
    fp = hashlib.sha256(pw_hash.encode()).hexdigest()[:12]
    body = f"{user_id}.{exp}.{fp}"
    sig = hmac.new(SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_token(tok: str):
    """returns (user_id, fingerprint) or None"""
    try:
        uid, exp, fp, sig = tok.split('.')
        body = f"{uid}.{exp}.{fp}"
        good = hmac.new(SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(good, sig) or int(exp) < time.time():
            return None
        return int(uid), fp
    except Exception:
        return None


def fingerprint(pw_hash: str) -> str:
    return hashlib.sha256(pw_hash.encode()).hexdigest()[:12]
