"""Описание форм и таблиц веб-интерфейса; разбор и валидация отправленных форм."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.web.templating import _date, _money

Options = Callable[[Session], list[tuple[Any, str]]]


@dataclass
class Field:
    name: str
    label: str
    type: str = "text"  # text, textarea, date, number, select, checkbox, email, password
    required: bool = False
    options: Options | None = None
    wide: bool = False
    hint: str | None = None
    kinds: tuple[m.ItemKind, ...] | None = None  # для позиций: показывать только для этих видов учёта


def _enum_options(labels: dict) -> Options:
    return lambda db: [(k.value, v) for k, v in labels.items()]


def _query_options(model, order, label=str, where=None) -> Options:
    def options(db: Session):
        stmt = select(model).order_by(*order)
        if where is not None:
            stmt = stmt.where(where)
        return [(o.id, label(o)) for o in db.scalars(stmt)]

    return options


organizations = _query_options(m.Organization, [m.Organization.name])
counterparties = _query_options(m.Counterparty, [m.Counterparty.name])
contracts = _query_options(m.Contract, [m.Contract.date.desc()], lambda c: f"{c} — {c.subject[:60]}")
employees = _query_options(
    m.Employee, [m.Employee.last_name, m.Employee.first_name],
    lambda e: f"{e.full_name}" + (f", {e.position}" if e.position else ""),
    where=m.Employee.is_active.is_(True),
)
categories = _query_options(m.Category, [m.Category.kind, m.Category.name],
                            lambda c: f"{m.ITEM_KIND_LABELS[c.kind]}: {c.name}")

REQUISITES = [
    Field("inn", "ИНН", hint="10 или 12 цифр"),
    Field("kpp", "КПП", hint="9 цифр"),
    Field("ogrn", "ОГРН / ОГРНИП"),
]

LICENSE = (m.ItemKind.LICENSE,)
HARDWARE = (m.ItemKind.COMPUTER, m.ItemKind.OFFICE)

FORMS: dict[str, list[Field]] = {
    "organizations": [
        Field("name", "Полное наименование", required=True, wide=True),
        Field("short_name", "Краткое наименование"),
        Field("head_name", "Руководитель (ФИО)"),
        *REQUISITES,
        Field("address", "Адрес", wide=True),
    ],
    "counterparties": [
        Field("name", "Наименование", required=True, wide=True),
        *REQUISITES,
        Field("contact_person", "Контактное лицо"),
        Field("phone", "Телефон"),
        Field("email", "Эл. почта", "email"),
        Field("address", "Адрес", wide=True),
        Field("bank_details", "Банковские реквизиты", "textarea", wide=True),
    ],
    "employees": [
        Field("last_name", "Фамилия", required=True),
        Field("first_name", "Имя", required=True),
        Field("middle_name", "Отчество"),
        Field("organization_id", "Организация", "select", required=True, options=organizations),
        Field("position", "Должность"),
        Field("department", "Подразделение"),
        Field("email", "Эл. почта", "email"),
        Field("phone", "Телефон"),
        Field("is_active", "Работает", "checkbox"),
    ],
    "contracts": [
        Field("number", "Номер контракта", required=True),
        Field("date", "Дата заключения", "date", required=True),
        Field("law", "Основание", "select", required=True, options=_enum_options(m.CONTRACT_LAW_LABELS)),
        Field("amount", "Цена контракта, ₽", "number"),
        Field("ikz", "ИКЗ", hint="Идентификационный код закупки — 36 цифр"),
        Field("registry_number", "Реестровый номер в ЕИС"),
        Field("subject", "Предмет контракта", "textarea", required=True, wide=True),
        Field("organization_id", "Заказчик", "select", required=True, options=organizations),
        Field("counterparty_id", "Поставщик", "select", required=True, options=counterparties),
        Field("valid_from", "Действует с", "date"),
        Field("valid_to", "Действует по", "date"),
        Field("notes", "Примечание", "textarea", wide=True),
    ],
    "categories": [
        Field("kind", "Вид учёта", "select", required=True, options=_enum_options(m.ITEM_KIND_LABELS)),
        Field("name", "Наименование категории", required=True),
    ],
    "items": [
        Field("kind", "Вид учёта", "select", required=True, options=_enum_options(m.ITEM_KIND_LABELS)),
        Field("category_id", "Категория", "select", options=categories),
        Field("name", "Наименование", required=True, wide=True),
        Field("inventory_number", "Инвентарный номер"),
        Field("serial_number", "Серийный номер", kinds=HARDWARE + (m.ItemKind.FURNITURE,)),
        Field("manufacturer", "Производитель / правообладатель"),
        Field("model", "Модель / редакция"),
        Field("license_key", "Лицензионный ключ / номер", kinds=LICENSE, wide=True),
        Field("seats", "Количество рабочих мест", "number", kinds=LICENSE),
        Field("valid_until", "Срок действия лицензии", "date", kinds=LICENSE),
        Field("price", "Стоимость, ₽", "number"),
        Field("acquired_at", "Дата принятия к учёту", "date"),
        Field("warranty_until", "Гарантия до", "date", kinds=HARDWARE),
        Field("organization_id", "Балансодержатель", "select", required=True, options=organizations),
        Field("contract_id", "Госконтракт", "select", options=contracts),
        Field("counterparty_id", "Поставщик", "select", options=counterparties),
        Field("location", "Местонахождение (кабинет)"),
        Field("notes", "Примечание", "textarea", wide=True),
    ],
}

# Колонки таблиц справочников: (заголовок, функция получения значения)
COLUMNS: dict[str, list[tuple[str, Callable]]] = {
    "organizations": [("Наименование", lambda o: o.short_name or o.name), ("ИНН", lambda o: o.inn),
                      ("КПП", lambda o: o.kpp), ("Руководитель", lambda o: o.head_name)],
    "counterparties": [("Наименование", lambda o: o.name), ("ИНН", lambda o: o.inn),
                       ("Контактное лицо", lambda o: o.contact_person), ("Телефон", lambda o: o.phone)],
    "employees": [("ФИО", lambda o: o.full_name), ("Должность", lambda o: o.position),
                  ("Подразделение", lambda o: o.department), ("Организация", lambda o: str(o.organization)),
                  ("Статус", lambda o: "работает" if o.is_active else "уволен")],
    "contracts": [("Номер", lambda o: o.number), ("Дата", lambda o: _date(o.date)),
                  ("Предмет", lambda o: o.subject), ("Поставщик", lambda o: str(o.counterparty)),
                  ("Цена", lambda o: _money(o.amount)), ("Закон", lambda o: m.CONTRACT_LAW_LABELS[o.law])],
    "categories": [("Вид учёта", lambda o: m.ITEM_KIND_LABELS[o.kind]), ("Категория", lambda o: o.name)],
}

USER_FIELDS = [
    Field("username", "Логин", required=True, hint="Латинские буквы, цифры, «_ . @ -»"),
    Field("role", "Роль", "select", required=True, options=_enum_options(m.ROLE_LABELS)),
    Field("employee_id", "Сотрудник", "select", options=employees,
          hint="Обязательно для менеджера и руководителя — владелец электронной подписи"),
    Field("password", "Пароль", "password", hint="Не менее 8 символов. При редактировании — оставьте пустым, "
                                                 "чтобы не менять"),
    Field("is_active", "Учётная запись активна", "checkbox"),
]


def values_from(obj, fields: list[Field]) -> dict:
    values = {}
    for f in fields:
        value = getattr(obj, f.name, None)
        values[f.name] = value.value if hasattr(value, "value") else value
    return values


def raw_values(form, fields: list[Field]) -> dict:
    data: dict[str, Any] = {}
    for f in fields:
        if f.type == "checkbox":
            data[f.name] = f.name in form
            continue
        value = (form.get(f.name) or "").strip()
        if f.type == "number" and value:
            value = value.replace(" ", "").replace(" ", "").replace(",", ".")
        data[f.name] = value or None
    return data


_MESSAGES = {
    "missing": "Обязательное поле",
    "string_too_short": "Обязательное поле",
    "string_pattern_mismatch": "Неверный формат",
    "date_from_datetime_parsing": "Неверная дата",
    "date_parsing": "Неверная дата",
    "int_parsing": "Введите целое число",
    "decimal_parsing": "Введите число",
    "greater_than_equal": "Значение слишком мало",
    "decimal_max_places": "Не более двух знаков после запятой",
    "enum": "Выберите значение из списка",
    "too_short": "Выберите хотя бы одну позицию",
}


def validate(schema: type[BaseModel], data: dict) -> tuple[BaseModel | None, dict[str, str]]:
    try:
        return schema.model_validate(data), {}
    except ValidationError as exc:
        errors = {}
        for err in exc.errors():
            key = str(err["loc"][0]) if err["loc"] else "__all__"
            message = _MESSAGES.get(err["type"]) or err["msg"].removeprefix("Value error, ")
            if data.get(key) is None and err["type"] not in ("too_short",) and key != "__all__":
                message = "Обязательное поле"
            errors.setdefault(key, message)
        return None, errors
