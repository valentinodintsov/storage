from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session

from app.errors import Forbidden, NotFound, ServiceError
from app.models import (
    ACTIVE_WAYBILL_STATUSES,
    ITEM_STATUS_LABELS,
    AuditLog,
    Item,
    ItemKind,
    ItemStatus,
    Role,
    Signature,
    SignerRole,
    User,
    Waybill,
    WaybillLine,
)
from app.schemas import ItemIn, ItemStatusIn
from app.services import audit, crud

# Допустимые переходы статуса вне накладных (выдача/возврат оформляются только накладной)
STATUS_TRANSITIONS = {
    ItemStatus.IN_STOCK: {ItemStatus.REPAIR, ItemStatus.WRITTEN_OFF},
    ItemStatus.REPAIR: {ItemStatus.IN_STOCK, ItemStatus.WRITTEN_OFF},
    ItemStatus.ISSUED: set(),
    ItemStatus.WRITTEN_OFF: set(),
}


def list_items(
    db: Session,
    user: User,
    *,
    kind: ItemKind | None = None,
    status: ItemStatus | None = None,
    holder_id: int | None = None,
    organization_id: int | None = None,
    contract_id: int | None = None,
    q: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[Item]:
    stmt = select(Item)
    if user.role == Role.USER:
        # Пользователь видит только закреплённое за ним имущество
        if not user.employee_id:
            return []
        holder_id = user.employee_id
    if kind:
        stmt = stmt.where(Item.kind == kind)
    if status:
        stmt = stmt.where(Item.status == status)
    if holder_id:
        stmt = stmt.where(Item.holder_id == holder_id)
    if organization_id:
        stmt = stmt.where(Item.organization_id == organization_id)
    if contract_id:
        stmt = stmt.where(Item.contract_id == contract_id)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Item.name.ilike(pattern),
                Item.inventory_number.ilike(pattern),
                Item.serial_number.ilike(pattern),
                Item.model.ilike(pattern),
                Item.manufacturer.ilike(pattern),
            )
        )
    return list(db.scalars(stmt.order_by(Item.id.desc()).limit(limit).offset(offset)))


def get_item(db: Session, user: User, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise NotFound("Позиция не найдена")
    if user.role == Role.USER and item.holder_id != user.employee_id:
        raise Forbidden()
    return item


def _check_category(db: Session, payload: ItemIn) -> None:
    if payload.category_id:
        category = crud.get_entity(db, crud.REFERENCES["categories"].model, payload.category_id)
        if category.kind != payload.kind:
            raise ServiceError("Категория не соответствует виду учёта")


def create_item(db: Session, user: User, payload: ItemIn) -> Item:
    _check_category(db, payload)
    return crud.create_entity(db, user, Item, payload)


def update_item(db: Session, user: User, item: Item, payload: ItemIn) -> Item:
    _check_category(db, payload)
    if item.status == ItemStatus.WRITTEN_OFF:
        raise ServiceError("Списанная позиция не редактируется")
    if payload.organization_id != item.organization_id and item.status == ItemStatus.ISSUED:
        raise ServiceError("Нельзя сменить балансодержателя у выданной позиции")
    return crud.update_entity(db, user, item, payload)


def visible_waybills(user: User):
    """Условие видимости накладных: руководитель видит накладную только после подписи МОЛ."""
    if user.role != Role.HEAD:
        return true()
    return Waybill.signatures.any(Signature.signer_role == SignerRole.MANAGER)


def active_waybill_for(db: Session, item_id: int, exclude_waybill_id: int | None = None) -> Waybill | None:
    stmt = (
        select(Waybill)
        .join(WaybillLine)
        .where(WaybillLine.item_id == item_id, Waybill.status.in_(ACTIVE_WAYBILL_STATUSES))
    )
    if exclude_waybill_id:
        stmt = stmt.where(Waybill.id != exclude_waybill_id)
    return db.scalars(stmt).first()


def change_status(db: Session, user: User, item: Item, payload: ItemStatusIn) -> Item:
    if payload.status not in STATUS_TRANSITIONS[item.status]:
        raise ServiceError(
            f"Переход «{ITEM_STATUS_LABELS[item.status]}» → «{ITEM_STATUS_LABELS[payload.status]}» недопустим"
            + (". Сначала оформите возврат на склад" if item.status == ItemStatus.ISSUED else "")
        )
    if waybill := active_waybill_for(db, item.id):
        raise ServiceError(f"Позиция включена в незавершённую накладную № {waybill.number}")
    old = item.status
    item.status = payload.status
    audit.log(
        db, user, "status", "items", item.id,
        f"{ITEM_STATUS_LABELS[old]} → {ITEM_STATUS_LABELS[item.status]}: {payload.reason}",
    )
    db.commit()
    return item


def delete_item(db: Session, user: User, item: Item) -> None:
    if db.scalar(select(WaybillLine.id).where(WaybillLine.item_id == item.id).limit(1)):
        raise ServiceError("Позиция фигурирует в накладных; удаление невозможно, используйте списание")
    crud.delete_entity(db, user, item)


def item_history(db: Session, user: User, item: Item) -> dict:
    waybills = list(
        db.scalars(
            select(Waybill).join(WaybillLine)
            .where(WaybillLine.item_id == item.id, visible_waybills(user))
            .order_by(Waybill.date.desc())
        )
    )
    events = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.entity == "items", AuditLog.entity_id == item.id)
            .order_by(AuditLog.at.desc())
        )
    )
    return {"waybills": waybills, "events": events}
