from sqlalchemy.orm import Session

from app.models import AuditLog, User


def log(db: Session, user: User | None, action: str, entity: str, entity_id: int | None, details: str = "") -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            action=action,
            entity=entity,
            entity_id=entity_id,
            details=details or None,
        )
    )
