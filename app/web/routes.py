"""Веб-интерфейс (серверная отрисовка, работает в любом современном браузере без установки)."""

from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app.config import settings
from app.db import get_db
from app.errors import Forbidden, ServiceError
from app.schemas import ItemIn, ItemStatusIn, SignIn, UserIn, WaybillIn
from app.security import (
    CAN_EDIT_ASSETS,
    CAN_VIEW_ALL,
    COOKIE_NAME,
    authenticate,
    create_token,
    get_current_user,
    require_roles,
)
from app.services import crud, items as items_svc, signatures, users as users_svc, waybills as waybills_svc
from app.web import forms
from app.web.forms import FORMS, USER_FIELDS
from app.web.templating import redirect, render

router = APIRouter(include_in_schema=False)

staff = require_roles(*CAN_VIEW_ALL)
editors = require_roles(*CAN_EDIT_ASSETS)
admins = require_roles(m.Role.ADMIN)


def _enum_or_none(enum_cls, value: str | None):
    try:
        return enum_cls(value) if value else None
    except ValueError:
        return None


def _int_or_none(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def _options(db: Session, fields: list[forms.Field]) -> dict:
    return {f.name: f.options(db) for f in fields if f.options}


def _form_page(request, user, db, *, title, fields, values, errors=None, action, back, submit="Сохранить",
               extra=None):
    return render(
        request, "form.html", user,
        status_code=400 if errors else 200,
        title=title, fields=fields, values=values, errors=errors or {}, options=_options(db, fields),
        action=action, back=back, submit=submit, extra=extra,
    )


# --- Вход ------------------------------------------------------------------


@router.get("/login")
def login_page(request: Request, next: str = "/"):
    return render(request, "login.html", next=next, error=None)


@router.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    next_url = str(form.get("next") or "/")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"
    user = authenticate(db, str(form.get("username", "")), str(form.get("password", "")))
    if not user:
        return render(request, "login.html", next=next_url, error="Неверный логин или пароль",
                      username=form.get("username", ""), status_code=401)
    response = redirect(next_url)
    response.set_cookie(COOKIE_NAME, create_token(user), httponly=True, samesite="lax",
                        secure=settings.cookie_secure, max_age=settings.token_ttl_minutes * 60)
    return response


@router.get("/logout")
def logout():
    response = redirect("/login")
    response.delete_cookie(COOKIE_NAME)
    return response


# --- Главная ---------------------------------------------------------------


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    context = {}
    if user.role in CAN_VIEW_ALL:
        rows = db.execute(select(m.Item.kind, m.Item.status, func.count()).group_by(m.Item.kind, m.Item.status))
        stats = {kind: {s: 0 for s in m.ItemStatus} for kind in m.ItemKind}
        for kind, status, count in rows:
            stats[kind][status] = count
        context["stats"] = stats
        context["total_amount"] = db.scalar(
            select(func.coalesce(func.sum(m.Item.price), 0)).where(m.Item.status != m.ItemStatus.WRITTEN_OFF)
        )
        waiting_status = {m.Role.MANAGER: m.WaybillStatus.DRAFT, m.Role.HEAD: m.WaybillStatus.MANAGER_SIGNED}
        if user.role in waiting_status:
            context["to_sign"] = waybills_svc.list_waybills(db, user, status=waiting_status[user.role], limit=20)
        context["recent"] = waybills_svc.list_waybills(db, user, limit=8)
        context["expiring"] = list(db.scalars(
            select(m.Item).where(m.Item.kind == m.ItemKind.LICENSE, m.Item.valid_until.is_not(None),
                                 m.Item.status != m.ItemStatus.WRITTEN_OFF)
            .order_by(m.Item.valid_until).limit(5)
        ))
    if user.employee_id:
        context["my_items"] = items_svc.list_items(db, user, holder_id=user.employee_id)
        context["to_confirm"] = [
            w for w in waybills_svc.list_waybills(db, user, status=m.WaybillStatus.APPROVED,
                                                  employee_id=user.employee_id)
            if w.receiver_id == user.employee_id
        ]
    return render(request, "dashboard.html", user, today=date.today(), **context)


# --- Справочники -----------------------------------------------------------


@router.get("/refs/{slug}")
def ref_list(slug: str, request: Request, q: str | None = None, db: Session = Depends(get_db),
             user: m.User = Depends(staff)):
    ref = crud.get_reference(slug)
    rows = crud.list_entities(db, ref, q)
    return render(request, "refs/list.html", user, ref=ref, rows=rows, columns=forms.COLUMNS[slug], q=q or "",
                  can_edit=user.role in CAN_EDIT_ASSETS)


@router.get("/refs/{slug}/new")
def ref_new(slug: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(editors)):
    ref = crud.get_reference(slug)
    values = {"is_active": True, "law": m.ContractLaw.FZ44.value}
    return _form_page(request, user, db, title=f"{ref.title}: новая запись", fields=FORMS[slug], values=values,
                      action=f"/refs/{slug}/new", back=f"/refs/{slug}")


@router.post("/refs/{slug}/new")
async def ref_create(slug: str, request: Request, db: Session = Depends(get_db), user: m.User = Depends(editors)):
    ref = crud.get_reference(slug)
    values = forms.raw_values(await request.form(), FORMS[slug])
    payload, errors = forms.validate(ref.schema_in, values)
    if payload:
        try:
            crud.create_entity(db, user, ref.model, payload)
            return redirect(f"/refs/{slug}", "Запись добавлена")
        except ServiceError as exc:
            errors = {"__all__": exc.message}
    return _form_page(request, user, db, title=f"{ref.title}: новая запись", fields=FORMS[slug], values=values,
                      errors=errors, action=f"/refs/{slug}/new", back=f"/refs/{slug}")


@router.get("/refs/{slug}/{entity_id}/edit")
def ref_edit(slug: str, entity_id: int, request: Request, db: Session = Depends(get_db),
             user: m.User = Depends(editors)):
    ref = crud.get_reference(slug)
    obj = crud.get_entity(db, ref.model, entity_id)
    return _form_page(request, user, db, title=f"{ref.title}: {obj}", fields=FORMS[slug],
                      values=forms.values_from(obj, FORMS[slug]), action=f"/refs/{slug}/{entity_id}/edit",
                      back=f"/refs/{slug}", extra={"delete_url": f"/refs/{slug}/{entity_id}/delete"})


@router.post("/refs/{slug}/{entity_id}/edit")
async def ref_update(slug: str, entity_id: int, request: Request, db: Session = Depends(get_db),
                     user: m.User = Depends(editors)):
    ref = crud.get_reference(slug)
    obj = crud.get_entity(db, ref.model, entity_id)
    values = forms.raw_values(await request.form(), FORMS[slug])
    payload, errors = forms.validate(ref.schema_in, values)
    if payload:
        try:
            crud.update_entity(db, user, obj, payload)
            return redirect(f"/refs/{slug}", "Изменения сохранены")
        except ServiceError as exc:
            errors = {"__all__": exc.message}
    return _form_page(request, user, db, title=f"{ref.title}: {obj}", fields=FORMS[slug], values=values,
                      errors=errors, action=f"/refs/{slug}/{entity_id}/edit", back=f"/refs/{slug}",
                      extra={"delete_url": f"/refs/{slug}/{entity_id}/delete"})


@router.post("/refs/{slug}/{entity_id}/delete")
def ref_delete(slug: str, entity_id: int, db: Session = Depends(get_db), user: m.User = Depends(editors)):
    ref = crud.get_reference(slug)
    try:
        crud.delete_entity(db, user, crud.get_entity(db, ref.model, entity_id))
    except ServiceError as exc:
        return redirect(f"/refs/{slug}/{entity_id}/edit", exc.message, "error")
    return redirect(f"/refs/{slug}", "Запись удалена")


# --- Учётные позиции -------------------------------------------------------


@router.get("/items")
def item_list(request: Request, kind: str | None = None, status: str | None = None, holder_id: str | None = None,
              contract_id: str | None = None, q: str | None = None,
              db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    filters = dict(kind=_enum_or_none(m.ItemKind, kind), status=_enum_or_none(m.ItemStatus, status),
                   holder_id=_int_or_none(holder_id), contract_id=_int_or_none(contract_id), q=q)
    rows = items_svc.list_items(db, user, **filters)
    return render(request, "items/list.html", user, rows=rows, filters=filters,
                  employees=forms.employees(db) if user.role in CAN_VIEW_ALL else [],
                  can_edit=user.role in CAN_EDIT_ASSETS)


@router.get("/items/new")
def item_new(request: Request, kind: str | None = None, db: Session = Depends(get_db),
             user: m.User = Depends(editors)):
    values = {"kind": (_enum_or_none(m.ItemKind, kind) or m.ItemKind.COMPUTER).value,
              "acquired_at": date.today()}
    orgs = forms.organizations(db)
    if len(orgs) == 1:
        values["organization_id"] = orgs[0][0]
    return _form_page(request, user, db, title="Новая учётная позиция", fields=FORMS["items"], values=values,
                      action="/items/new", back="/items")


@router.post("/items/new")
async def item_create(request: Request, db: Session = Depends(get_db), user: m.User = Depends(editors)):
    form = await request.form()
    values = forms.raw_values(form, FORMS["items"])
    payload, errors = forms.validate(ItemIn, values)
    if payload:
        try:
            item = items_svc.create_item(db, user, payload)
            if form.get("then") == "more":
                return redirect(f"/items/new?kind={item.kind.value}", f"Позиция «{item.name}» добавлена")
            return redirect(f"/items/{item.id}", "Позиция поставлена на учёт")
        except ServiceError as exc:
            errors = {"__all__": exc.message}
    return _form_page(request, user, db, title="Новая учётная позиция", fields=FORMS["items"], values=values,
                      errors=errors, action="/items/new", back="/items")


@router.get("/items/{item_id}")
def item_detail(item_id: int, request: Request, db: Session = Depends(get_db),
                user: m.User = Depends(get_current_user)):
    item = items_svc.get_item(db, user, item_id)
    history = items_svc.item_history(db, user, item) if user.role in CAN_VIEW_ALL else {"waybills": [], "events": []}
    return render(request, "items/detail.html", user, item=item, history=history,
                  can_edit=user.role in CAN_EDIT_ASSETS,
                  transitions=sorted(items_svc.STATUS_TRANSITIONS[item.status], key=lambda s: s.value))


@router.get("/items/{item_id}/edit")
def item_edit(item_id: int, request: Request, db: Session = Depends(get_db), user: m.User = Depends(editors)):
    item = items_svc.get_item(db, user, item_id)
    return _form_page(request, user, db, title=f"Редактирование: {item}", fields=FORMS["items"],
                      values=forms.values_from(item, FORMS["items"]), action=f"/items/{item_id}/edit",
                      back=f"/items/{item_id}")


@router.post("/items/{item_id}/edit")
async def item_update(item_id: int, request: Request, db: Session = Depends(get_db),
                      user: m.User = Depends(editors)):
    item = items_svc.get_item(db, user, item_id)
    values = forms.raw_values(await request.form(), FORMS["items"])
    payload, errors = forms.validate(ItemIn, values)
    if payload:
        try:
            items_svc.update_item(db, user, item, payload)
            return redirect(f"/items/{item_id}", "Изменения сохранены")
        except ServiceError as exc:
            errors = {"__all__": exc.message}
    return _form_page(request, user, db, title=f"Редактирование: {item}", fields=FORMS["items"], values=values,
                      errors=errors, action=f"/items/{item_id}/edit", back=f"/items/{item_id}")


@router.post("/items/{item_id}/status")
async def item_status(item_id: int, request: Request, db: Session = Depends(get_db),
                      user: m.User = Depends(editors)):
    item = items_svc.get_item(db, user, item_id)
    form = await request.form()
    payload, errors = forms.validate(ItemStatusIn, {"status": form.get("status"),
                                                    "reason": (form.get("reason") or "").strip() or None})
    if errors:
        return redirect(f"/items/{item_id}", "Укажите причину смены статуса", "error")
    try:
        items_svc.change_status(db, user, item, payload)
    except ServiceError as exc:
        return redirect(f"/items/{item_id}", exc.message, "error")
    return redirect(f"/items/{item_id}", "Статус изменён")


@router.post("/items/{item_id}/delete")
def item_delete(item_id: int, db: Session = Depends(get_db), user: m.User = Depends(editors)):
    item = items_svc.get_item(db, user, item_id)
    try:
        items_svc.delete_item(db, user, item)
    except ServiceError as exc:
        return redirect(f"/items/{item_id}", exc.message, "error")
    return redirect("/items", "Позиция удалена")


# --- Накладные -------------------------------------------------------------


@router.get("/waybills")
def waybill_list(request: Request, status: str | None = None, type: str | None = None,
                 db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    filters = dict(status=_enum_or_none(m.WaybillStatus, status), type_=_enum_or_none(m.WaybillType, type))
    rows = waybills_svc.list_waybills(db, user, **filters)
    return render(request, "waybills/list.html", user, rows=rows, filters=filters,
                  can_edit=user.role in CAN_EDIT_ASSETS)


def _waybill_values(user: m.User, db: Session, params) -> dict:
    type_ = _enum_or_none(m.WaybillType, params.get("type")) or m.WaybillType.ISSUE
    orgs = forms.organizations(db)
    org_id = _int_or_none(params.get("organization_id"))
    if org_id is None:
        org_id = user.employee.organization_id if user.employee else (orgs[0][0] if orgs else None)
    values = {
        "type": type_,
        "date": params.get("date") or date.today().isoformat(),
        "organization_id": org_id,
        "sender_id": _int_or_none(params.get("sender_id")),
        "receiver_id": _int_or_none(params.get("receiver_id")),
        "basis": params.get("basis") or "",
        "notes": params.get("notes") or "",
        "item_ids": [int(v) for v in params.getlist("item_ids") if v.isdigit()],
    }
    # МОЛ по умолчанию — сдаёт при выдаче и принимает при возврате
    if user.employee_id:
        if type_ == m.WaybillType.ISSUE and values["sender_id"] is None:
            values["sender_id"] = user.employee_id
        if type_ == m.WaybillType.RETURN and values["receiver_id"] is None:
            values["receiver_id"] = user.employee_id
    return values


def _waybill_form(request, user, db, values, *, action, title, errors=None, waybill=None):
    org_id = values["organization_id"]
    staff_list = list(db.scalars(
        select(m.Employee).where(m.Employee.organization_id == org_id, m.Employee.is_active.is_(True))
        .order_by(m.Employee.last_name, m.Employee.first_name)
    )) if org_id else []
    candidates: list[m.Item] = []
    if org_id:
        stmt = select(m.Item).where(m.Item.organization_id == org_id).order_by(m.Item.kind, m.Item.name)
        if values["type"] == m.WaybillType.ISSUE:
            stmt = stmt.where(m.Item.status == m.ItemStatus.IN_STOCK)
        elif values["sender_id"]:
            stmt = stmt.where(m.Item.status == m.ItemStatus.ISSUED, m.Item.holder_id == values["sender_id"])
        else:
            stmt = stmt.where(False)
        exclude = waybill.id if waybill else None
        candidates = [i for i in db.scalars(stmt) if not items_svc.active_waybill_for(db, i.id, exclude)]
    return render(request, "waybills/form.html", user, status_code=400 if errors else 200,
                  values=values, errors=errors or {}, organizations=forms.organizations(db), employees=staff_list,
                  candidates=candidates, action=action, title=title, waybill=waybill)


async def _waybill_submit(request: Request, db: Session, user: m.User, waybill: m.Waybill | None):
    form = await request.form()
    values = _waybill_values(user, db, form)
    action = f"/waybills/{waybill.id}/edit" if waybill else "/waybills/new"
    title = f"Редактирование: {waybill}" if waybill else "Новая накладная"
    if form.get("reload"):
        return _waybill_form(request, user, db, values, action=action, title=title, waybill=waybill)
    payload, errors = forms.validate(WaybillIn, {**values, "basis": values["basis"] or None,
                                                 "notes": values["notes"] or None})
    if payload:
        try:
            if waybill:
                result = waybills_svc.update_waybill(db, user, waybill, payload)
            else:
                result = waybills_svc.create_waybill(db, user, payload)
            return redirect(f"/waybills/{result.id}", "Накладная сохранена. Проверьте и подпишите документ")
        except ServiceError as exc:
            db.rollback()
            errors = {"__all__": exc.message}
    return _waybill_form(request, user, db, values, action=action, title=title, errors=errors, waybill=waybill)


@router.get("/waybills/new")
def waybill_new(request: Request, db: Session = Depends(get_db), user: m.User = Depends(editors)):
    values = _waybill_values(user, db, request.query_params)
    return _waybill_form(request, user, db, values, action="/waybills/new", title="Новая накладная")


@router.post("/waybills/new")
async def waybill_create(request: Request, db: Session = Depends(get_db), user: m.User = Depends(editors)):
    return await _waybill_submit(request, db, user, None)


@router.get("/waybills/{waybill_id}")
def waybill_detail(waybill_id: int, request: Request, db: Session = Depends(get_db),
                   user: m.User = Depends(get_current_user)):
    waybill = waybills_svc.get_waybill(db, user, waybill_id)
    signer_role = waybills_svc.next_signer_role(user, waybill)
    checks = {s.id: signatures.verify_signature(waybill, s) for s in waybill.signatures}
    return render(request, "waybills/detail.html", user, w=waybill, signer_role=signer_role, checks=checks,
                  provider=signatures.provider_for(signer_role).name if signer_role else None,
                  can_edit=user.role in CAN_EDIT_ASSETS,
                  revocable={s.id for s in waybill.signatures if waybills_svc.can_revoke(user, waybill, s)})


@router.get("/waybills/{waybill_id}/edit")
def waybill_edit(waybill_id: int, request: Request, db: Session = Depends(get_db), user: m.User = Depends(editors)):
    waybill = waybills_svc.get_waybill(db, user, waybill_id)
    if waybill.status != m.WaybillStatus.DRAFT:
        return redirect(f"/waybills/{waybill_id}", "Редактировать можно только черновик", "error")
    values = {
        "type": waybill.type, "date": waybill.date.isoformat(), "organization_id": waybill.organization_id,
        "sender_id": waybill.sender_id, "receiver_id": waybill.receiver_id, "basis": waybill.basis or "",
        "notes": waybill.notes or "", "item_ids": [line.item_id for line in waybill.lines],
    }
    return _waybill_form(request, user, db, values, action=f"/waybills/{waybill_id}/edit",
                         title=f"Редактирование: {waybill}", waybill=waybill)


@router.post("/waybills/{waybill_id}/edit")
async def waybill_update(waybill_id: int, request: Request, db: Session = Depends(get_db),
                         user: m.User = Depends(editors)):
    return await _waybill_submit(request, db, user, waybills_svc.get_waybill(db, user, waybill_id))


@router.post("/waybills/{waybill_id}/sign")
async def waybill_sign(waybill_id: int, request: Request, db: Session = Depends(get_db),
                       user: m.User = Depends(get_current_user)):
    waybill = waybills_svc.get_waybill(db, user, waybill_id)
    form = await request.form()
    data = SignIn(signature=form.get("signature") or None, certificate=form.get("certificate") or None,
                  password=form.get("password") or None)
    try:
        waybills_svc.sign_waybill(db, user, waybill, data)
    except Forbidden as exc:
        return redirect(f"/waybills/{waybill_id}", exc.message, "error")
    except ServiceError as exc:
        db.rollback()
        return redirect(f"/waybills/{waybill_id}", exc.message, "error")
    return redirect(f"/waybills/{waybill_id}", "Документ подписан")


@router.post("/waybills/{waybill_id}/cancel")
def waybill_cancel(waybill_id: int, db: Session = Depends(get_db), user: m.User = Depends(editors)):
    try:
        waybills_svc.cancel_waybill(db, user, waybills_svc.get_waybill(db, user, waybill_id))
    except ServiceError as exc:
        return redirect(f"/waybills/{waybill_id}", exc.message, "error")
    return redirect(f"/waybills/{waybill_id}", "Накладная отменена")


@router.post("/waybills/{waybill_id}/signatures/{signature_id}/revoke")
async def waybill_revoke(waybill_id: int, signature_id: int, request: Request, db: Session = Depends(get_db),
                         user: m.User = Depends(get_current_user)):
    form = await request.form()
    try:
        waybills_svc.revoke_signature(db, user, waybills_svc.get_waybill(db, user, waybill_id), signature_id,
                                      str(form.get("reason") or ""))
    except ServiceError as exc:
        db.rollback()
        return redirect(f"/waybills/{waybill_id}", exc.message, "error")
    return redirect(f"/waybills/{waybill_id}", "Подпись отменена")


@router.post("/waybills/{waybill_id}/delete")
async def waybill_delete(waybill_id: int, request: Request, db: Session = Depends(get_db),
                         user: m.User = Depends(editors)):
    form = await request.form()
    try:
        waybills_svc.delete_waybill(db, user, waybills_svc.get_waybill(db, user, waybill_id),
                                    str(form.get("reason") or ""))
    except ServiceError as exc:
        db.rollback()
        return redirect(f"/waybills/{waybill_id}", exc.message, "error")
    return redirect("/waybills", "Накладная удалена")


@router.get("/waybills/{waybill_id}/print")
def waybill_print(waybill_id: int, request: Request, db: Session = Depends(get_db),
                  user: m.User = Depends(get_current_user)):
    waybill = waybills_svc.get_waybill(db, user, waybill_id)
    checks = {s.id: signatures.verify_signature(waybill, s) for s in waybill.signatures}
    return render(request, "waybills/print.html", user, w=waybill, checks=checks)


# --- Пользователи и журнал -------------------------------------------------


@router.get("/users")
def user_list(request: Request, db: Session = Depends(get_db), user: m.User = Depends(admins)):
    return render(request, "users/list.html", user, rows=users_svc.list_users(db))


@router.get("/users/new")
def user_new(request: Request, db: Session = Depends(get_db), user: m.User = Depends(admins)):
    return _form_page(request, user, db, title="Новый пользователь", fields=USER_FIELDS,
                      values={"is_active": True, "role": m.Role.USER.value}, action="/users/new", back="/users")


@router.post("/users/new")
async def user_create(request: Request, db: Session = Depends(get_db), user: m.User = Depends(admins)):
    values = forms.raw_values(await request.form(), USER_FIELDS)
    payload, errors = forms.validate(UserIn, values)
    if payload:
        try:
            users_svc.create_user(db, user, payload)
            return redirect("/users", "Пользователь создан")
        except ServiceError as exc:
            errors = {"__all__": exc.message}
    values["password"] = None
    return _form_page(request, user, db, title="Новый пользователь", fields=USER_FIELDS, values=values,
                      errors=errors, action="/users/new", back="/users")


@router.get("/users/{user_id}/edit")
def user_edit(user_id: int, request: Request, db: Session = Depends(get_db), user: m.User = Depends(admins)):
    target = crud.get_entity(db, m.User, user_id)
    values = forms.values_from(target, USER_FIELDS) | {"password": None}
    return _form_page(request, user, db, title=f"Пользователь {target.username}", fields=USER_FIELDS,
                      values=values, action=f"/users/{user_id}/edit", back="/users")


@router.post("/users/{user_id}/edit")
async def user_update(user_id: int, request: Request, db: Session = Depends(get_db), user: m.User = Depends(admins)):
    target = crud.get_entity(db, m.User, user_id)
    values = forms.raw_values(await request.form(), USER_FIELDS)
    payload, errors = forms.validate(UserIn, values)
    if payload:
        try:
            users_svc.update_user(db, user, target, payload)
            return redirect("/users", "Изменения сохранены")
        except ServiceError as exc:
            db.rollback()
            errors = {"__all__": exc.message}
    values["password"] = None
    return _form_page(request, user, db, title=f"Пользователь {target.username}", fields=USER_FIELDS,
                      values=values, errors=errors, action=f"/users/{user_id}/edit", back="/users")


@router.get("/audit")
def audit_log(request: Request, entity: str | None = None, db: Session = Depends(get_db),
              user: m.User = Depends(require_roles(m.Role.ADMIN, m.Role.HEAD))):
    stmt = select(m.AuditLog).order_by(m.AuditLog.id.desc()).limit(300)
    if entity:
        stmt = stmt.where(m.AuditLog.entity == entity)
    return render(request, "audit.html", user, rows=list(db.scalars(stmt)), entity=entity or "")
