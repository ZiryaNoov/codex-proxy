"""JWT authentication middleware and endpoints for codex-proxy v5.

Provides:
- Password hashing with bcrypt
- JWT access + refresh tokens
- FastAPI dependency for route protection
- Auto-seeding admin user on first startup
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("codex-proxy.auth")

# ── Password hashing ────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash a password using bcrypt. Falls back to SHA-256 if bcrypt unavailable."""
    try:
        import bcrypt
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    except ImportError:
        # Fallback for systems without bcrypt
        salt = secrets.token_hex(16)
        h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return f"sha256${salt}${h}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    if password_hash.startswith("$2b$") or password_hash.startswith("$2a$"):
        try:
            import bcrypt
            return bcrypt.checkpw(password.encode(), password_hash.encode())
        except ImportError:
            return False
    elif password_hash.startswith("sha256$"):
        parts = password_hash.split("$", 2)
        if len(parts) != 3:
            return False
        salt = parts[1]
        stored_hash = parts[2]
        check = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return secrets.compare_digest(check, stored_hash)
    return False


# ── JWT tokens ──────────────────────────────────────────────────────────

def _get_jwt_impl():
    """Lazy-import JWT. Returns (encode, decode, ExpiredSignatureError, InvalidTokenError)."""
    try:
        import jwt
        return jwt.encode, jwt.decode, jwt.ExpiredSignatureError, jwt.InvalidTokenError
    except ImportError:
        # Minimal fallback — HMAC-SHA256 with stdlib
        import base64
        import hashlib as hl
        import hmac
        import json

        def _b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        def _b64url_decode(s: str) -> bytes:
            padding = 4 - len(s) % 4
            if padding != 4:
                s += "=" * padding
            return base64.urlsafe_b64decode(s)

        def encode_f(payload: dict, key: str, algorithm: str = "HS256") -> str:
            header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
            body = _b64url(json.dumps(payload, default=str).encode())
            sig = hmac.new(key.encode(), f"{header}.{body}".encode(), hl.sha256).digest()
            return f"{header}.{body}.{_b64url(sig)}"

        class ExpiredError(Exception):
            pass

        class InvalidError(Exception):
            pass

        def decode_f(token: str, key: str, algorithms: list | None = None) -> dict:
            try:
                parts = token.split(".")
                if len(parts) != 3:
                    raise InvalidError("Invalid token format")
                header, body, sig = parts
                expected_sig = hmac.new(
                    key.encode(), f"{header}.{body}".encode(), hl.sha256
                ).digest()
                actual_sig = _b64url_decode(sig)
                if not hmac.compare_digest(expected_sig, actual_sig):
                    raise InvalidError("Invalid signature")
                payload = json.loads(_b64url_decode(body))
                if "exp" in payload:
                    exp = datetime.fromisoformat(payload["exp"].replace("Z", "+00:00")) \
                        if isinstance(payload["exp"], str) \
                        else datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
                    if datetime.now(timezone.utc) > exp:
                        raise ExpiredError("Token expired")
                return payload
            except ExpiredError:
                raise
            except Exception as e:
                raise InvalidError(str(e)) from e

        return encode_f, decode_f, ExpiredError, InvalidError


_jwt_encode, _jwt_decode, _ExpiredError, _InvalidError = None, None, None, None


def _init_jwt():
    global _jwt_encode, _jwt_decode, _ExpiredError, _InvalidError
    if _jwt_encode is None:
        _jwt_encode, _jwt_decode, _ExpiredError, _InvalidError = _get_jwt_impl()


def create_access_token(data: dict, secret_key: str, expires_minutes: int = 15) -> str:
    """Create a JWT access token."""
    _init_jwt()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    })
    return _jwt_encode(to_encode, secret_key, algorithm="HS256")


def create_refresh_token(data: dict, secret_key: str, expires_days: int = 7) -> str:
    """Create a JWT refresh token."""
    _init_jwt()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=expires_days)
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    })
    return _jwt_encode(to_encode, secret_key, algorithm="HS256")


def decode_token(token: str, secret_key: str) -> dict[str, Any]:
    """Decode and validate a JWT token. Raises on invalid/expired."""
    _init_jwt()
    try:
        payload = _jwt_decode(token, secret_key, algorithms=["HS256"])
        return payload
    except _ExpiredError:
        raise ValueError("Token expired")
    except _InvalidError:
        raise ValueError("Invalid token")


# ── FastAPI dependencies ────────────────────────────────────────────────

class AuthUser:
    """Authenticated user info attached to requests."""
    def __init__(self, user_id: str, username: str, role: str):
        self.user_id = user_id
        self.username = username
        self.role = role

    def __repr__(self) -> str:
        return f"AuthUser(id={self.user_id}, username={self.username}, role={self.role})"


def get_current_user(authorization: str = ""):
    """FastAPI dependency that extracts and validates the current user from JWT.

    Returns None if auth is disabled. Raises HTTPException(401) on bad token.
    """
    from fastapi import HTTPException

    async def _dependency(authorization: str = "") -> AuthUser | None:
        from .server import _state
        state = _state()

        # Auth disabled — no user context
        if not state.config.auth.enabled:
            return None

        # Auth enabled — token required
        if not authorization:
            raise HTTPException(status_code=401, detail="Authorization header required")

        token = authorization
        if token.lower().startswith("bearer "):
            token = token[7:].strip()

        try:
            payload = decode_token(token, state.config.auth.secret_key)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))

        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")

        user_id = payload.get("sub")
        username = payload.get("username")
        role = payload.get("role", "user")

        if not user_id or not username:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        return AuthUser(user_id=user_id, username=username, role=role)

    return _dependency


# ── Admin seeding ───────────────────────────────────────────────────────

async def seed_admin_user(db_session_factory, config) -> None:
    """Create the initial admin user if no users exist."""
    from .db import crud_users

    async with db_session_factory() as session:
        count = await crud_users.count_users(session)
        if count > 0:
            return

        password = config.auth.admin_password or "changeme"
        pw_hash = hash_password(password)
        await crud_users.create_user(
            session,
            username=config.auth.admin_username,
            email=None,
            password_hash=pw_hash,
            role="admin",
        )
        logger.info("Seeded admin user: %s", config.auth.admin_username)
        if not config.auth.admin_password:
            logger.warning("Admin password not set — using default 'changeme'. "
                           "Change it immediately via PUT /auth/users/me/password")


def ensure_secret_key(config) -> str:
    """Ensure a secret key exists for JWT signing. Returns the key."""
    if config.auth.secret_key:
        return config.auth.secret_key
    key = secrets.token_urlsafe(32)
    config.auth.secret_key = key
    logger.warning("Generated random JWT secret key. Set [auth] secret_key in config for persistence.")
    return key
