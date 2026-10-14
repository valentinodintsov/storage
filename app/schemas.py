"""Схемы ввода/вывода. Используются и REST API, и веб-интерфейсом."""

from datetime import date as Date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.models import (
    ContractLaw,
    ItemKind,
    ItemStatus,
    Role,
    SignerRole,
    WaybillStatus,
    WaybillType,
)


def _checksum(digits: str, coefs: list[int]) -> int:
    return sum(int(d) * c for d, c in zip(digits, coefs)) % 11 % 10


def validate_inn(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.isdigit() or len(value) not in (10, 12):
        raise ValueError("ИНН должен состоять из 10 или 12 цифр")
    if len(value) == 10:
        ok = _checksum(value, [2, 4, 10, 3, 5, 9, 4, 6, 8]) == int(value[9])
    else:
        ok = _checksum(value, [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == int(value[10]) and _checksum(
            value, [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        ) == int(value[11])
    if not ok:
        raise ValueError("Неверная контрольная сумма ИНН")
    return value


Inn = Annotated[str | None, AfterValidator(validate_inn)]
Kpp = Annotated[str | None, Field(pattern=r"^\d{9}$")]
Ogrn = Annotated[str | None, Field(pattern=r"^(\d{13}|\d{15})$")]
Str = Annotated[str, Field(min_length=1, max_length=500)]
OptStr = Annotated[str | None, Field(max_length=500)]
Money = Annotated[Decimal | None, Field(ge=0, max_digits=15, decimal_places=2)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Справочники -----------------------------------------------------------


class OrganizationIn(BaseModel):
    name: Str
    short_name: OptStr = None
    inn: Inn = None
    kpp: Kpp = None
    ogrn: Ogrn = None
    address: OptStr = None
    head_name: OptStr = None


class OrganizationOut(OrganizationIn, ORM):
    id: int


class CounterpartyIn(BaseModel):
    name: Str
    inn: Inn = None
    kpp: Kpp = None
    ogrn: Ogrn = None
    address: OptStr = None
    contact_person: OptStr = None
    phone: OptStr = None
    email: OptStr = None
    bank_details: str | None = None


class CounterpartyOut(CounterpartyIn, ORM):
    id: int


class EmployeeIn(BaseModel):
    organization_id: int
    last_name: Str
    first_name: Str
    middle_name: OptStr = None
    position: OptStr = None
    department: OptStr = None
    email: OptStr = None
    phone: OptStr = None
    is_active: bool = True


class EmployeeOut(EmployeeIn, ORM):
    id: int
    full_name: str


class CategoryIn(BaseModel):
    kind: ItemKind
    name: Str


class CategoryOut(CategoryIn, ORM):
    id: int


class ContractIn(BaseModel):
    number: Str
    date: Date
    ikz: Annotated[str | None, Field(pattern=r"^\d{36}$")] = None
    registry_number: OptStr = None
    law: ContractLaw = ContractLaw.FZ44
    subject: Str
    amount: Money = None
    organization_id: int
    counterparty_id: int
    valid_from: Date | None = None
    valid_to: Date | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_period(self):
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("Дата окончания действия контракта раньше даты начала")
        return self


class ContractOut(ContractIn, ORM):
    id: int


# --- Учётные позиции -------------------------------------------------------


class ItemIn(BaseModel):
    kind: ItemKind
    category_id: int | None = None
    name: Str
    inventory_number: Annotated[str | None, Field(max_length=100)] = None
    serial_number: OptStr = None
    manufacturer: OptStr = None
    model: OptStr = None
    price: Money = None
    acquired_at: Date | None = None
    warranty_until: Date | None = None
    license_key: OptStr = None
    seats: Annotated[int | None, Field(ge=1)] = None
    valid_until: Date | None = None
    organization_id: int
    contract_id: int | None = None
    counterparty_id: int | None = None
    location: OptStr = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_kind(self):
        if self.kind != ItemKind.LICENSE:
            self.license_key = self.seats = self.valid_until = None
        elif not self.seats:
            self.seats = 1
        return self


class ItemStatusIn(BaseModel):
    """Смена статуса вне накладной: ремонт, возврат из ремонта, списание."""

    status: ItemStatus
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class ItemOut(ItemIn, ORM):
    id: int
    status: ItemStatus
    holder_id: int | None
    created_at: datetime
    updated_at: datetime


# --- Накладные -------------------------------------------------------------


class WaybillIn(BaseModel):
    type: WaybillType
    date: Date
    organization_id: int
    sender_id: int
    receiver_id: int
    item_ids: Annotated[list[int], Field(min_length=1)]
    basis: OptStr = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_parties(self):
        if self.sender_id == self.receiver_id:
            raise ValueError("Отправитель и получатель должны различаться")
        self.item_ids = list(dict.fromkeys(self.item_ids))
        return self


class WaybillLineOut(ORM):
    item_id: int
    name: str
    inventory_number: str | None
    serial_number: str | None
    price: Decimal | None


class SignatureOut(ORM):
    signer_role: SignerRole
    user_id: int
    provider: str
    digest: str
    certificate: str | None
    signed_at: datetime


class WaybillOut(ORM):
    id: int
    number: str
    date: Date
    type: WaybillType
    status: WaybillStatus
    organization_id: int
    sender_id: int
    receiver_id: int
    created_by_id: int
    basis: str | None
    notes: str | None
    lines: list[WaybillLineOut]
    signatures: list[SignatureOut]


class SignIn(BaseModel):
    """Подпись документа. Для провайдера cades — откреплённая подпись CMS (base64), сформированная клиентом."""

    signature: str | None = None
    certificate: str | None = None
    password: str | None = None  # повторный ввод пароля для простой ЭП


class SignDocument(BaseModel):
    """Данные документа, которые подписываются ЭП."""

    digest: str
    content_base64: str
    provider: str


# --- Пользователи ----------------------------------------------------------


class UserIn(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_.@-]+$")]
    role: Role
    employee_id: int | None = None
    is_active: bool = True
    password: Annotated[str | None, Field(min_length=8, max_length=128)] = None


class UserOut(ORM):
    id: int
    username: str
    role: Role
    employee_id: int | None
    is_active: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
