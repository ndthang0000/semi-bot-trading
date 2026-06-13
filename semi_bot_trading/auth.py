"""Authentication utilities: JWT token management, password hashing, refresh token DB ops.

Usage
-----
Generate a password hash (run once):
    semi-bot hash-password

Then add the printed hash to .env as ADMIN_PASSWORD_HASH.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection
from typing import Any

ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=7)
ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Password
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Return a bcrypt hash string suitable for storing in .env / DB."""
    import bcrypt  # lazy import — optional dep at module level

    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed* bcrypt string."""
    import bcrypt

    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------

def create_access_token(username: str, secret_key: str) -> str:
    """Create a short-lived access token (15 min)."""
    import jwt

    now = datetime.now(UTC)
    payload = {
        "sub": username,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + ACCESS_TOKEN_TTL).timestamp()),
    }
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def create_refresh_token(username: str, secret_key: str) -> str:
    """Create a long-lived refresh token (7 days) with a unique jti."""
    import jwt

    now = datetime.now(UTC)
    payload = {
        "sub": username,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + REFRESH_TOKEN_TTL).timestamp()),
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def decode_token(token: str, secret_key: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises jwt.PyJWTError on any failure."""
    import jwt

    return jwt.decode(token, secret_key, algorithms=[ALGORITHM])


# ---------------------------------------------------------------------------
# Refresh token DB ops
# ---------------------------------------------------------------------------

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def store_refresh_token(conn: Connection, token: str, username: str) -> None:
    """Persist a refresh token (hash only) so it can be invalidated later."""
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    expires_at = (datetime.now(UTC) + REFRESH_TOKEN_TTL).replace(microsecond=0).isoformat()
    conn.execute(
        """
        INSERT INTO auth_refresh_tokens (id, username, token_hash, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (secrets.token_hex(16), username, _token_hash(token), expires_at, now),
    )
    conn.commit()


def revoke_refresh_token(conn: Connection, token: str) -> None:
    """Mark a specific refresh token as revoked."""
    conn.execute(
        "UPDATE auth_refresh_tokens SET revoked = 1 WHERE token_hash = ?",
        (_token_hash(token),),
    )
    conn.commit()


def is_refresh_token_valid(conn: Connection, token: str) -> bool:
    """Return True if the token exists, is not revoked, and has not expired."""
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    row = conn.execute(
        """
        SELECT id FROM auth_refresh_tokens
        WHERE token_hash = ? AND revoked = 0 AND expires_at > ?
        """,
        (_token_hash(token), now),
    ).fetchone()
    return row is not None


def purge_expired_refresh_tokens(conn: Connection) -> None:
    """Delete expired / revoked tokens (call periodically to keep the table small)."""
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    conn.execute(
        "DELETE FROM auth_refresh_tokens WHERE expires_at <= ? OR revoked = 1",
        (now,),
    )
    conn.commit()
