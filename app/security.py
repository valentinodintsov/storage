import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import Forbidden, NotAuthenticated
from app.models import Role, User

COOKIE_NAME = "access_token"
_PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
    return hmac.compare_digest(candidate, digest)


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "exp": datetime.now(UTC) + timedelta(minutes=settings.token_ttl_minutes),
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm="HS256")


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).one_or_none()
    if user and user.is_active and verify_password(password, user.password_hash):
        return user
    return None


def _token_from_request(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return request.cookies.get(COOKIE_NAME)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _token_from_request(request)
    if not token:
        raise NotAuthenticated()
    try:
        payload = jwt.decode(token, settings.secret_key.get_secret_value(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise NotAuthenticated()
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise NotAuthenticated()
    return user


def require_roles(*roles: Role):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise Forbidden()
        return user

    return dependency


# Наборы ролей для типовых операций
CAN_EDIT_ASSETS = (Role.ADMIN, Role.MANAGER)
CAN_VIEW_ALL = (Role.ADMIN, Role.MANAGER, Role.HEAD)
