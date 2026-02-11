"""
Authentication utilities: password hashing, JWT tokens, and current-user dependency.
Uses cookie-based JWT for seamless server-rendered page auth.
"""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-please")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


# ---------------------------------------------------------------------------
# Password helpers (using bcrypt directly)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(user_id: int, role: str) -> str:
    """Create a signed JWT containing the user id and role."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Decode a JWT token. Returns payload dict or None if invalid."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def create_reset_token(email: str) -> str:
    """Create a password reset token valid for 15 minutes."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {"sub": email, "type": "reset", "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_reset_token(token: str) -> str | None:
    """Verify a reset token and return the email if valid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "reset":
            return None
        return payload.get("sub")
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Extract the JWT from the 'access_token' cookie, validate it,
    and return the corresponding User object.
    Redirects to login page if not authenticated.
    """
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/connexion"},
        )
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/connexion"},
        )
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/connexion"},
        )
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Same as get_current_user but returns None instead of raising."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = decode_token(token)
    if payload is None:
        return None
    return db.query(User).filter(User.id == int(payload["sub"])).first()


def require_senior(user: User = Depends(get_current_user)) -> User:
    """Dependency that ensures the current user is a senior."""
    if user.role.value != "senior":
        raise HTTPException(status_code=403, detail="Accès réservé aux seniors.")
    return user
