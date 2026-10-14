from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import ServiceError
from app.models import Employee, Role, User
from app.schemas import UserIn
from app.security import hash_password
from app.services import audit


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.username)))


def _check(db: Session, payload: UserIn, user_id: int | None = None) -> None:
    if payload.employee_id is not None:
        if db.get(Employee, payload.employee_id) is None:
            raise ServiceError("Сотрудник не найден")
        other = db.scalar(select(User).where(User.employee_id == payload.employee_id))
        if other and other.id != user_id:
            raise ServiceError(f"Сотрудник уже связан с учётной записью {other.username}")
    if payload.role in (Role.MANAGER, Role.HEAD) and payload.employee_id is None:
        raise ServiceError("Менеджеру и руководителю необходимо указать сотрудника — владельца подписи")


def create_user(db: Session, actor: User, payload: UserIn) -> User:
    if not payload.password:
        raise ServiceError("Укажите пароль (не менее 8 символов)")
    _check(db, payload)
    if db.scalar(select(User).where(User.username == payload.username)):
        raise ServiceError("Логин уже занят")
    user = User(
        username=payload.username,
        role=payload.role,
        employee_id=payload.employee_id,
        is_active=payload.is_active,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()
    audit.log(db, actor, "create", "users", user.id, f"{user.username} ({user.role.value})")
    db.commit()
    return user


def update_user(db: Session, actor: User, user: User, payload: UserIn) -> User:
    _check(db, payload, user.id)
    if user.id == actor.id and (payload.role != Role.ADMIN or not payload.is_active):
        raise ServiceError("Нельзя лишить себя прав администратора или заблокировать свою учётную запись")
    if payload.username != user.username and db.scalar(select(User).where(User.username == payload.username)):
        raise ServiceError("Логин уже занят")
    user.username = payload.username
    user.role = payload.role
    user.employee_id = payload.employee_id
    user.is_active = payload.is_active
    details = f"{user.username} ({user.role.value}, активна: {user.is_active})"
    if payload.password:
        user.password_hash = hash_password(payload.password)
        details += ", пароль изменён"
    audit.log(db, actor, "update", "users", user.id, details)
    db.commit()
    return user


def ensure_admin(db: Session) -> None:
    """Создаёт учётную запись администратора при первом запуске."""
    if db.scalar(select(User).where(User.role == Role.ADMIN).limit(1)):
        return
    db.add(
        User(
            username=settings.admin_username,
            role=Role.ADMIN,
            password_hash=hash_password(settings.admin_password.get_secret_value()),
        )
    )
    db.commit()

