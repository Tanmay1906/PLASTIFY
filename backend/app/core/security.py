"""PLASTIFY Core Security and Cryptography Utilities.

Provides bcrypt password hashing, JWT encoding/decoding, and token hashing.
Ensures secrets and passwords are never stored in plaintext.
"""

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any, Dict, Optional, Tuple, Union
import uuid
import bcrypt
import jwt

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedException


def hash_password(password: str) -> str:
    """Hash plaintext password securely using bcrypt with 12 rounds."""
    # Bcrypt truncates passwords over 72 bytes; encode and enforce safe slice
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    try:
        pwd_bytes = plain_password.encode("utf-8")[:72]
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except Exception:
        return False


def hash_token(raw_token: str) -> str:
    """Generate SHA-256 digest of a token for secure database storage.

    Prevents raw refresh tokens from being exposed in case of read-only DB compromise.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_access_token(
    subject: Union[str, uuid.UUID],
    claims: Optional[Dict[str, Any]] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Encode a short-lived signed JWT access token."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: Dict[str, Any] = {
        "sub": str(subject),
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if claims:
        payload.update(claims)

    encoded = jwt.encode(
        payload,
        settings.effective_jwt_secret_key,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded


def create_refresh_token(
    subject: Union[str, uuid.UUID],
    token_family: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> Tuple[str, str, datetime]:
    """Encode a cryptographically signed JWT refresh token.

    Returns:
        (raw_token_string, token_family_id, expires_at_datetime)
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    family_id = token_family or str(uuid.uuid4())
    jti = str(uuid.uuid4())

    payload: Dict[str, Any] = {
        "sub": str(subject),
        "type": "refresh",
        "family": family_id,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }

    raw_token = jwt.encode(
        payload,
        settings.effective_jwt_secret_key,
        algorithm=settings.JWT_ALGORITHM,
    )
    return raw_token, family_id, expire


def decode_token(token: str, expected_type: Optional[str] = None) -> Dict[str, Any]:
    """Decode and validate a JWT token's signature, expiration, and payload.

    Raises UnauthorizedException on any signature or expiration failure.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.effective_jwt_secret_key,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedException("Authentication token has expired.")
    except jwt.InvalidTokenError:
        raise UnauthorizedException("Invalid authentication token format or signature.")

    token_type = payload.get("type")
    if expected_type and token_type != expected_type:
        raise UnauthorizedException(
            f"Invalid token type: expected '{expected_type}', got '{token_type}'."
        )

    return payload
