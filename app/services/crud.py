"""Типовые операции со справочниками."""

from dataclasses import dataclass, field

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.errors import NotFound, ServiceError
from app.models import Category, Contract, Counterparty, Employee, Organization, User
from app.services import audit


@dataclass(frozen=True)
class Reference:
    slug: str
    model: type
    schema_in: type[BaseModel]
    schema_out: type[BaseModel]
    title: str
    search: tuple[str, ...]
    order_by: tuple[str, ...] = field(default=("id",))


REFERENCES = {
    r.slug: r
    for r in (
        Reference(
            "organizations", Organization, schemas.OrganizationIn, schemas.OrganizationOut,
            "Организации", ("name", "short_name", "inn"), ("name",),
        ),
        Reference(
            "counterparties", Counterparty, schemas.CounterpartyIn, schemas.CounterpartyOut,
            "Контрагенты", ("name", "inn", "contact_person"), ("name",),
        ),
        Reference(
            "employees", Employee, schemas.EmployeeIn, schemas.EmployeeOut,
            "Сотрудники", ("last_name", "first_name", "position", "department"), ("last_name", "first_name"),
        ),
        Reference(
            "contracts", Contract, schemas.ContractIn, schemas.ContractOut,
            "Госконтракты", ("number", "ikz", "subject", "registry_number"), ("date",),
        ),
        Reference(
            "categories", Category, schemas.CategoryIn, schemas.CategoryOut,
            "Категории", ("name",), ("kind", "name"),
        ),
    )
}


def get_reference(slug: str) -> Reference:
    try:
        return REFERENCES[slug]
    except KeyError:
        raise NotFound("Справочник не найден")


def list_entities(db: Session, ref: Reference, q: str | None = None, limit: int = 500, offset: int = 0) -> list:
    stmt = select(ref.model)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(*(getattr(ref.model, c).ilike(pattern) for c in ref.search)))
    order = [getattr(ref.model, c) for c in ref.order_by]
    if ref.model is Contract:
        order = [Contract.date.desc()]
    return list(db.scalars(stmt.order_by(*order).limit(limit).offset(offset)))


def get_entity(db: Session, model: type, entity_id: int):
    obj = db.get(model, entity_id)
    if obj is None:
        raise NotFound()
    return obj


def _check_foreign_keys(db: Session, model: type, data: dict) -> None:
    for fk in model.__table__.foreign_keys:
        value = data.get(fk.parent.name)
        if value is None:
            continue
        target = next(m for m in _all_models() if m.__table__ is fk.column.table)
        if db.get(target, value) is None:
            raise ServiceError(f"Связанный объект не найден ({fk.parent.name}={value})")


def _all_models():
    from app.db import Base

    return [m.class_ for m in Base.registry.mappers]


def _commit(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ServiceError(message)


def create_entity(db: Session, user: User, model: type, payload: BaseModel):
    data = payload.model_dump()
    _check_foreign_keys(db, model, data)
    columns = {c.name for c in model.__table__.columns}
    obj = model(**{k: v for k, v in data.items() if k in columns})
    db.add(obj)
    db.flush()
    audit.log(db, user, "create", model.__tablename__, obj.id, str(obj))
    _commit(db, "Запись с такими реквизитами уже существует")
    return obj


def update_entity(db: Session, user: User, obj, payload: BaseModel):
    data = payload.model_dump()
    _check_foreign_keys(db, type(obj), data)
    columns = {c.name for c in type(obj).__table__.columns}
    changes = []
    for key, value in data.items():
        if key in columns and getattr(obj, key) != value:
            changes.append(f"{key}: {getattr(obj, key)!s} → {value!s}")
            setattr(obj, key, value)
    if changes:
        audit.log(db, user, "update", type(obj).__tablename__, obj.id, "; ".join(changes))
    _commit(db, "Запись с такими реквизитами уже существует")
    return obj


def delete_entity(db: Session, user: User, obj) -> None:
    audit.log(db, user, "delete", type(obj).__tablename__, obj.id, str(obj))
    db.delete(obj)
    _commit(db, "Запись используется в других документах и не может быть удалена")
