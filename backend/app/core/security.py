import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Set, Union
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from app.core.config import settings

# Initialize Argon2 PasswordHasher (defaults to Argon2id)
ph = PasswordHasher()

# Thread-safe in-memory token revocation blocklist
_revocation_lock = threading.Lock()
_revoked_tokens: Set[str] = set()


def revoke_token(token: str) -> None:
    """Revoke a token so it cannot be used again."""
    if not token:
        return
    with _revocation_lock:
        _revoked_tokens.add(token)


def is_token_revoked(token: str) -> bool:
    """Check if token is in the revoked blocklist."""
    if not token:
        return True
    with _revocation_lock:
        return token in _revoked_tokens


def get_password_hash(password: str) -> str:
    """Hash a password using Argon2id."""
    return ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against an Argon2id hash."""
    try:
        return ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError):
        return False
    except Exception:
        return False


def create_access_token(
    subject: Union[str, int],
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[Dict[str, Any]] = None
) -> str:
    """Create a signed JWT access token with a unique jti."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode: Dict[str, Any] = {
        "sub": str(subject),
        "jti": secrets.token_hex(16),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp())
    }

    if extra_claims:
        to_encode.update(extra_claims)

    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate a JWT access token, verifying it is not revoked."""
    if is_token_revoked(token):
        return None

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except jwt.PyJWTError:
        return None
