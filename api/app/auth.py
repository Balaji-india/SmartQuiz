"""Password hashing, JWT tokens and the get_current_user dependency."""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

JWT_ALGORITHM = "HS256"
TOKEN_LIFETIME = timedelta(days=7)

_hasher = PasswordHasher()
_bearer = HTTPBearer(auto_error=False)
# Verified when the email is unknown, so both login failures take about the same time.
_DUMMY_HASH = _hasher.hash("smartquiz-no-such-user")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (Argon2Error, InvalidHashError):
        return False


def _secret() -> str:
    secret = get_settings().jwt_secret
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth is not configured: JWT_SECRET is empty")
    return secret


def create_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user_id), "iat": now, "exp": now + TOKEN_LIFETIME}
    return jwt.encode(claims, _secret(), algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if credentials is None:
        raise unauthorized
    secret = _secret()
    try:
        claims = jwt.decode(
            credentials.credentials, secret, algorithms=[JWT_ALGORITHM], options={"require": ["exp", "sub"]}
        )
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError):
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None:
        raise unauthorized
    return user
