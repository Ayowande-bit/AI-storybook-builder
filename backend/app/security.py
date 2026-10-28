
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

# Load environment variables from backend/.env
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE, override=True)

# Password hashing
password_hash = PasswordHash.recommended()

# JWT configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 30


def hash_password(password: str) -> str:
    """Hash a password securely before storing it."""
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Check a password against its stored hash."""
    return password_hash.verify(password, hashed_password)


def create_access_token(
    user_id: int,
    expires_minutes: int = ACCESS_TOKEN_MINUTES,
) -> str:
    """Create a signed JWT access token for a user."""
    if not JWT_SECRET_KEY:
        raise RuntimeError(
            "JWT_SECRET_KEY is missing. Check backend/.env."
        )

    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    """Verify a JWT and return its payload."""
    if not JWT_SECRET_KEY:
        raise RuntimeError(
            "JWT_SECRET_KEY is missing. Check backend/.env."
        )

    return jwt.decode(
        token,
        JWT_SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "exp", "iat"]},
    )
