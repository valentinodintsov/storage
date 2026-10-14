"""Накладные: составление, подписание МОЛ и руководителем, подтверждение получения.

Маршрут документа:
    черновик → (подпись МОЛ) → подписана МОЛ → (подпись руководителя) → утверждена
    → (подтверждение получателем) → получение подтверждено.
Движение имущества (смена статуса и ответственного) выполняется при утверждении руководителем.

Подписант может отменить свою последнюю подпись, администратор — любую (вместе с ней отменяются
все последующие). Отмена подписи руководителя возвращает имущество в исходное состояние.
"""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.errors import Forbidden, NotFound, ServiceError
from app.models import (
    ACTIVE_WAYBILL_STATUSES,
    ITEM_STATUS_LABELS,
    Employee,
    Item,
    ItemStatus,
    Organization,
    SIGNER_ROLE_LABELS,
    Role,
    Signature,
    SignerRole,
    User,
    Waybill,
    WaybillLine,
    WaybillStatus,
    WaybillType,
)
from app.schemas import SignIn, WaybillIn
from app.services import audit, signatures
from app.services.items import active_waybill_for, visible_waybills


def list_waybills(
    db: Session,
    user: User,
    *,
    status: WaybillStatus | None = None,
    type_: WaybillType | None = None,
    employee_id: int | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[Waybill]:
    stmt = select(Waybill).where(visible_waybills(user))
    if user.role == Role.USER:
        if not user.employee_id:
            return []
        employee_id = user.employee_id
    if employee_id:
        stmt = stmt.where(or_(Waybill.sender_id == employee_id, Waybill.receiver_id == employee_id))
    if status:
        stmt = stmt.where(Waybill.status == status)
    if type_:
        stmt = stmt.where(Waybill.type == type_)
    return list(db.scalars(stmt.order_by(Waybill.date.desc(), Waybill.id.desc()).limit(limit).offset(offset)))


def get_waybill(db: Session, user: User, waybill_id: int) -> Waybill:
    waybill = db.get(Waybill, waybill_id)
    if waybill is None or (user.role == Role.HEAD and waybill.signature_of(SignerRole.MANAGER) is None):
        raise NotFound("Накладная не найдена")
    if user.role == Role.USER and user.employee_id not in (waybill.sender_id, waybill.receiver_id):
        raise Forbidden()
    return waybill


def _next_number(db: Session, year: int) -> str:
    prefix = f"{year}-"
    numbers = db.scalars(select(Waybill.number).where(Waybill.number.like(f"{prefix}%")))
    last = max((int(n[len(prefix):]) for n in numbers if n[len(prefix):].isdigit()), default=0)
    return f"{prefix}{last + 1:05d}"


def _employee(db: Session, employee_id: int, organization_id: int, role: str) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise ServiceError(f"{role}: сотрудник не найден")
    if not employee.is_active:
        raise ServiceError(f"{role}: сотрудник {employee.short_name} неактивен")
    if employee.organization_id != organization_id:
        raise ServiceError(f"{role}: сотрудник {employee.short_name} работает в другой организации")
    return employee


def _validate_items(db: Session, waybill_type: WaybillType, organization_id: int, sender_id: int,
                    item_ids: list[int], exclude_waybill_id: int | None = None) -> list[Item]:
    items = []
    for item_id in item_ids:
        item = db.get(Item, item_id)
        if item is None:
            raise ServiceError(f"Позиция #{item_id} не найдена")
        label = str(item)
        if item.organization_id != organization_id:
            raise ServiceError(f"{label}: числится на балансе другой организации")
        if waybill_type == WaybillType.ISSUE:
            if item.status != ItemStatus.IN_STOCK:
                raise ServiceError(f"{label}: выдать можно только позицию со склада "
                                   f"(текущий статус — «{ITEM_STATUS_LABELS[item.status]}»)")
        elif item.status != ItemStatus.ISSUED or item.holder_id != sender_id:
            raise ServiceError(f"{label}: не закреплена за сдающим сотрудником")
        if other := active_waybill_for(db, item.id, exclude_waybill_id):
            raise ServiceError(f"{label}: уже включена в накладную № {other.number}")
        items.append(item)
    return items


def _validate(db: Session, payload: WaybillIn, exclude_waybill_id: int | None = None) -> list[Item]:
    if db.get(Organization, payload.organization_id) is None:
        raise ServiceError("Организация не найдена")
    _employee(db, payload.sender_id, payload.organization_id, "Сдал")
    _employee(db, payload.receiver_id, payload.organization_id, "Принял")
    return _validate_items(db, payload.type, payload.organization_id, payload.sender_id,
                           payload.item_ids, exclude_waybill_id)


def _fill_lines(waybill: Waybill, items: list[Item]) -> None:
    waybill.lines = [
        WaybillLine(
            item_id=item.id,
            name=item.name,
            inventory_number=item.inventory_number,
            serial_number=item.serial_number,
            price=item.price,
        )
        for item in items
    ]


def create_waybill(db: Session, user: User, payload: WaybillIn) -> Waybill:
    items = _validate(db, payload)
    waybill = Waybill(
        number=_next_number(db, payload.date.year),
        date=payload.date,
        type=payload.type,
        organization_id=payload.organization_id,
        sender_id=payload.sender_id,
        receiver_id=payload.receiver_id,
        created_by_id=user.id,
        basis=payload.basis,
        notes=payload.notes,
    )
    _fill_lines(waybill, items)
    db.add(waybill)
    db.flush()
    audit.log(db, user, "create", "waybills", waybill.id, f"№ {waybill.number}, позиций: {len(items)}")
    db.commit()
    return waybill


def update_waybill(db: Session, user: User, waybill: Waybill, payload: WaybillIn) -> Waybill:
    if waybill.status != WaybillStatus.DRAFT:
        raise ServiceError("Редактировать можно только черновик")
    items = _validate(db, payload, exclude_waybill_id=waybill.id)
    for field in ("date", "type", "organization_id", "sender_id", "receiver_id", "basis", "notes"):
        setattr(waybill, field, getattr(payload, field))
    waybill.lines.clear()
    db.flush()
    _fill_lines(waybill, items)
    audit.log(db, user, "update", "waybills", waybill.id, f"позиций: {len(items)}")
    db.commit()
    db.refresh(waybill)
    return waybill


def next_signer_role(user: User, waybill: Waybill) -> SignerRole | None:
    """Какую подпись пользователь может поставить под документом сейчас (None — никакую)."""
    if user.role == Role.MANAGER and waybill.status == WaybillStatus.DRAFT:
        return SignerRole.MANAGER
    if user.role == Role.HEAD and waybill.status == WaybillStatus.MANAGER_SIGNED:
        return SignerRole.HEAD
    if (waybill.status == WaybillStatus.APPROVED and user.employee_id
            and user.employee_id == waybill.receiver_id):
        return SignerRole.RECEIVER
    return None


def _apply_movement(waybill: Waybill) -> None:
    for line in waybill.lines:
        item = line.item
        if waybill.type == WaybillType.RETURN:
            item.status = ItemStatus.IN_STOCK
            item.holder_id = None
        else:
            item.status = ItemStatus.ISSUED
            item.holder_id = waybill.receiver_id


def sign_waybill(db: Session, user: User, waybill: Waybill, data: SignIn) -> Waybill:
    role = next_signer_role(user, waybill)
    if role is None:
        raise Forbidden("Подписание недоступно: неподходящая роль или статус документа")

    if role in (SignerRole.MANAGER, SignerRole.HEAD):
        # Состояние имущества могло измениться с момента составления документа
        _validate_items(db, waybill.type, waybill.organization_id, waybill.sender_id,
                        [line.item_id for line in waybill.lines], exclude_waybill_id=waybill.id)
    if role == SignerRole.HEAD:
        manager_sig = waybill.signature_of(SignerRole.MANAGER)
        if manager_sig is None or signatures.verify_signature(waybill, manager_sig) is False:
            raise ServiceError("Подпись МОЛ недействительна: документ изменён после подписания или сертификат не прошёл проверку")

    sig = signatures.make_signature(user, role, waybill, data)
    waybill.signatures.append(sig)

    if role == SignerRole.MANAGER:
        waybill.status = WaybillStatus.MANAGER_SIGNED
    elif role == SignerRole.HEAD:
        waybill.status = WaybillStatus.APPROVED
        _apply_movement(waybill)
    else:
        waybill.status = WaybillStatus.RECEIVED

    audit.log(db, user, "sign", "waybills", waybill.id, f"№ {waybill.number}: подпись «{role.value}» ({sig.provider})")
    for line in waybill.lines:
        if role == SignerRole.HEAD:
            audit.log(db, user, "move", "items", line.item_id, f"по накладной № {waybill.number}")
    db.commit()
    return waybill


# Статус накладной по последней действующей подписи
_STATUS_AFTER = {
    None: WaybillStatus.DRAFT,
    SignerRole.MANAGER: WaybillStatus.MANAGER_SIGNED,
    SignerRole.HEAD: WaybillStatus.APPROVED,
    SignerRole.RECEIVER: WaybillStatus.RECEIVED,
}


def can_revoke(user: User, waybill: Waybill, sig: Signature) -> bool:
    """Подписант отменяет только свою последнюю подпись, администратор — любую."""
    if user.role == Role.ADMIN:
        return True
    return (waybill.status != WaybillStatus.CANCELLED and sig.user_id == user.id
            and sig is waybill.signatures[-1])


def _revert_movement(db: Session, waybill: Waybill) -> None:
    approval = waybill.signature_of(SignerRole.HEAD)
    for line in waybill.lines:
        item = line.item
        moved = (ItemStatus.IN_STOCK, None) if waybill.type == WaybillType.RETURN else (ItemStatus.ISSUED, waybill.receiver_id)
        if (item.status, item.holder_id) != moved or _later_waybill(db, item.id, waybill, approval):
            raise ServiceError(f"{item}: после утверждения накладной имущество уже перемещено или изменён его статус — "
                               "отмена подписи руководителя невозможна")
        if waybill.type == WaybillType.ISSUE:
            item.status, item.holder_id = ItemStatus.IN_STOCK, None
        else:
            item.status, item.holder_id = ItemStatus.ISSUED, waybill.sender_id


def _later_waybill(db: Session, item_id: int, waybill: Waybill, approval: Signature) -> Waybill | None:
    """Другая накладная по позиции — действующая или утверждённая позже данной (подписи нумеруются по порядку)."""
    stmt = (select(Waybill).join(WaybillLine)
            .where(WaybillLine.item_id == item_id, Waybill.id != waybill.id, Waybill.status != WaybillStatus.CANCELLED))
    for other in db.scalars(stmt):
        head = other.signature_of(SignerRole.HEAD)
        if other.status in ACTIVE_WAYBILL_STATUSES or (head and head.id > approval.id):
            return other
    return None


def _revoke(db: Session, user: User, waybill: Waybill, sig: Signature, reason: str) -> None:
    revoked = [s for s in waybill.signatures if s.id >= sig.id]
    if waybill.status != WaybillStatus.CANCELLED and any(s.signer_role == SignerRole.HEAD for s in revoked):
        _revert_movement(db, waybill)
        for line in waybill.lines:
            audit.log(db, user, "move", "items", line.item_id, f"отмена утверждения накладной № {waybill.number}")
    for s in reversed(revoked):
        signer = s.user.employee.full_name if s.user.employee else s.user.username
        audit.log(db, user, "revoke", "waybills", waybill.id,
                  f"№ {waybill.number}: отменена подпись «{SIGNER_ROLE_LABELS[s.signer_role]}» — {signer}, "
                  f"{s.provider}, {s.signed_at:%d.%m.%Y %H:%M}; {s.certificate or ''}. Причина: {reason}")
        waybill.signatures.remove(s)
    if waybill.status != WaybillStatus.CANCELLED:
        waybill.status = _STATUS_AFTER[waybill.signatures[-1].signer_role if waybill.signatures else None]


def revoke_signature(db: Session, user: User, waybill: Waybill, signature_id: int, reason: str) -> Waybill:
    sig = next((s for s in waybill.signatures if s.id == signature_id), None)
    if sig is None:
        raise NotFound("Подпись не найдена")
    if not can_revoke(user, waybill, sig):
        raise Forbidden("Отменить можно только свою последнюю подпись под документом")
    if not reason.strip():
        raise ServiceError("Укажите причину отмены подписи")
    _revoke(db, user, waybill, sig, reason.strip())
    db.commit()
    return waybill


def cancel_waybill(db: Session, user: User, waybill: Waybill, reason: str = "") -> Waybill:
    if user.role not in (Role.ADMIN, Role.MANAGER):
        raise Forbidden()
    if waybill.status not in ACTIVE_WAYBILL_STATUSES:
        raise ServiceError("Отменить можно только неутверждённую накладную")
    waybill.status = WaybillStatus.CANCELLED
    audit.log(db, user, "cancel", "waybills", waybill.id, f"№ {waybill.number}. {reason}".strip())
    db.commit()
    return waybill


def delete_waybill(db: Session, user: User, waybill: Waybill, reason: str = "") -> None:
    """Черновик без подписей удаляют администратор и менеджер; любую накладную — администратор."""
    reason = reason.strip()
    if user.role == Role.ADMIN and (waybill.status != WaybillStatus.DRAFT or waybill.signatures):
        if not reason:
            raise ServiceError("Укажите причину удаления накладной")
        if waybill.signatures:
            _revoke(db, user, waybill, waybill.signatures[0], reason)
    elif waybill.status != WaybillStatus.DRAFT or waybill.signatures:
        raise ServiceError("Удалить можно только черновик без подписей — сначала отмените подписи")
    audit.log(db, user, "delete", "waybills", waybill.id, f"№ {waybill.number}. {reason}".strip())
    db.delete(waybill)
    db.commit()
