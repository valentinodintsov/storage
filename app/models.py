"""Модель данных склада."""

import enum
from datetime import date as date_, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _enum(cls):
    # Храним значения перечислений (а не имена), чтобы в БД были читаемые коды
    return Enum(cls, values_callable=lambda e: [m.value for m in e], native_enum=False, length=32)


class Role(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    HEAD = "head"
    USER = "user"


ROLE_LABELS = {
    Role.ADMIN: "Администратор",
    Role.MANAGER: "Менеджер (МОЛ)",
    Role.HEAD: "Руководитель",
    Role.USER: "Пользователь",
}


class ItemKind(str, enum.Enum):
    COMPUTER = "computer"
    LICENSE = "license"
    OFFICE = "office"
    FURNITURE = "furniture"


ITEM_KIND_LABELS = {
    ItemKind.COMPUTER: "Компьютерная техника",
    ItemKind.LICENSE: "Лицензии на ПО",
    ItemKind.OFFICE: "Оргтехника",
    ItemKind.FURNITURE: "Мебель",
}


class ItemStatus(str, enum.Enum):
    IN_STOCK = "in_stock"
    ISSUED = "issued"
    REPAIR = "repair"
    WRITTEN_OFF = "written_off"


ITEM_STATUS_LABELS = {
    ItemStatus.IN_STOCK: "На складе",
    ItemStatus.ISSUED: "Выдано",
    ItemStatus.REPAIR: "В ремонте",
    ItemStatus.WRITTEN_OFF: "Списано",
}


class WaybillType(str, enum.Enum):
    ISSUE = "issue"
    RETURN = "return"
    TRANSFER = "transfer"


WAYBILL_TYPE_LABELS = {
    WaybillType.ISSUE: "Выдача сотруднику",
    WaybillType.RETURN: "Возврат на склад",
    WaybillType.TRANSFER: "Передача между сотрудниками",
}


class WaybillStatus(str, enum.Enum):
    DRAFT = "draft"
    MANAGER_SIGNED = "manager_signed"
    APPROVED = "approved"
    RECEIVED = "received"
    CANCELLED = "cancelled"


WAYBILL_STATUS_LABELS = {
    WaybillStatus.DRAFT: "Черновик",
    WaybillStatus.MANAGER_SIGNED: "Подписана МОЛ",
    WaybillStatus.APPROVED: "Утверждена руководителем",
    WaybillStatus.RECEIVED: "Получение подтверждено",
    WaybillStatus.CANCELLED: "Отменена",
}

ACTIVE_WAYBILL_STATUSES = (WaybillStatus.DRAFT, WaybillStatus.MANAGER_SIGNED)


class SignerRole(str, enum.Enum):
    MANAGER = "manager"
    HEAD = "head"
    RECEIVER = "receiver"


SIGNER_ROLE_LABELS = {
    SignerRole.MANAGER: "Материально ответственное лицо",
    SignerRole.HEAD: "Руководитель",
    SignerRole.RECEIVER: "Получатель",
}


class ContractLaw(str, enum.Enum):
    FZ44 = "44-FZ"
    FZ223 = "223-FZ"
    OTHER = "other"


CONTRACT_LAW_LABELS = {
    ContractLaw.FZ44: "44-ФЗ",
    ContractLaw.FZ223: "223-ФЗ",
    ContractLaw.OTHER: "Иное",
}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Organization(TimestampMixin, Base):
    """Государственная организация (заказчик, балансодержатель)."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(500))
    short_name: Mapped[str | None] = mapped_column(String(200))
    inn: Mapped[str | None] = mapped_column(String(12), unique=True)
    kpp: Mapped[str | None] = mapped_column(String(9))
    ogrn: Mapped[str | None] = mapped_column(String(15))
    address: Mapped[str | None] = mapped_column(String(500))
    head_name: Mapped[str | None] = mapped_column(String(200))

    def __str__(self) -> str:
        return self.short_name or self.name


class Counterparty(TimestampMixin, Base):
    """Контрагент (продавец, поставщик)."""

    __tablename__ = "counterparties"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(500))
    inn: Mapped[str | None] = mapped_column(String(12), unique=True)
    kpp: Mapped[str | None] = mapped_column(String(9))
    ogrn: Mapped[str | None] = mapped_column(String(15))
    address: Mapped[str | None] = mapped_column(String(500))
    contact_person: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(200))
    bank_details: Mapped[str | None] = mapped_column(Text)

    def __str__(self) -> str:
        return self.name


class Employee(TimestampMixin, Base):
    """Сотрудник организации, за которым закрепляются материальные ценности."""

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    last_name: Mapped[str] = mapped_column(String(100))
    first_name: Mapped[str] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100))
    position: Mapped[str | None] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    organization: Mapped[Organization] = relationship()
    items: Mapped[list["Item"]] = relationship(back_populates="holder")

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.last_name, self.first_name, self.middle_name) if p)

    @property
    def short_name(self) -> str:
        initials = "".join(f"{p[0]}." for p in (self.first_name, self.middle_name) if p)
        return f"{self.last_name} {initials}".strip()

    def __str__(self) -> str:
        return self.full_name


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[Role] = mapped_column(_enum(Role))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    employee: Mapped[Employee | None] = relationship()

    @property
    def display_name(self) -> str:
        return self.employee.short_name if self.employee else self.username

    def __str__(self) -> str:
        return self.display_name


class Contract(TimestampMixin, Base):
    """Государственный контракт (договор) на поставку."""

    __tablename__ = "contracts"
    __table_args__ = (UniqueConstraint("number", "date", name="uq_contract_number_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(100))
    date: Mapped[date_] = mapped_column(Date)
    ikz: Mapped[str | None] = mapped_column(String(36))  # идентификационный код закупки
    registry_number: Mapped[str | None] = mapped_column(String(50))  # реестровый номер в ЕИС
    law: Mapped[ContractLaw] = mapped_column(_enum(ContractLaw), default=ContractLaw.FZ44)
    subject: Mapped[str] = mapped_column(String(1000))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    counterparty_id: Mapped[int] = mapped_column(ForeignKey("counterparties.id"))
    valid_from: Mapped[date_ | None] = mapped_column(Date)
    valid_to: Mapped[date_ | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    organization: Mapped[Organization] = relationship()
    counterparty: Mapped[Counterparty] = relationship()

    def __str__(self) -> str:
        return f"№ {self.number} от {self.date:%d.%m.%Y}"


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("kind", "name", name="uq_category_kind_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[ItemKind] = mapped_column(_enum(ItemKind))
    name: Mapped[str] = mapped_column(String(200))

    def __str__(self) -> str:
        return self.name


class Item(TimestampMixin, Base):
    """Учётная единица: техника, лицензия, оргтехника, мебель."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[ItemKind] = mapped_column(_enum(ItemKind))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(String(500))
    inventory_number: Mapped[str | None] = mapped_column(String(100), unique=True)
    serial_number: Mapped[str | None] = mapped_column(String(200))
    manufacturer: Mapped[str | None] = mapped_column(String(200))
    model: Mapped[str | None] = mapped_column(String(200))
    price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    acquired_at: Mapped[date_ | None] = mapped_column(Date)
    warranty_until: Mapped[date_ | None] = mapped_column(Date)

    # Поля лицензий
    license_key: Mapped[str | None] = mapped_column(String(500))
    seats: Mapped[int | None] = mapped_column(Integer)
    valid_until: Mapped[date_ | None] = mapped_column(Date)

    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"))
    counterparty_id: Mapped[int | None] = mapped_column(ForeignKey("counterparties.id"))

    status: Mapped[ItemStatus] = mapped_column(_enum(ItemStatus), default=ItemStatus.IN_STOCK)
    holder_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    location: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    category: Mapped[Category | None] = relationship()
    organization: Mapped[Organization] = relationship()
    contract: Mapped[Contract | None] = relationship()
    counterparty: Mapped[Counterparty | None] = relationship()
    holder: Mapped[Employee | None] = relationship(back_populates="items")

    def __str__(self) -> str:
        return f"{self.name} ({self.inventory_number})" if self.inventory_number else self.name


class Waybill(TimestampMixin, Base):
    """Накладная на выдачу/возврат/внутреннее перемещение ценностей."""

    __tablename__ = "waybills"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(50), unique=True)
    date: Mapped[date_] = mapped_column(Date)
    type: Mapped[WaybillType] = mapped_column(_enum(WaybillType))
    status: Mapped[WaybillStatus] = mapped_column(_enum(WaybillStatus), default=WaybillStatus.DRAFT)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    sender_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    receiver_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    basis: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)

    organization: Mapped[Organization] = relationship()
    sender: Mapped[Employee] = relationship(foreign_keys=[sender_id])
    receiver: Mapped[Employee] = relationship(foreign_keys=[receiver_id])
    created_by: Mapped[User] = relationship()
    lines: Mapped[list["WaybillLine"]] = relationship(
        back_populates="waybill", cascade="all, delete-orphan", order_by="WaybillLine.id"
    )
    signatures: Mapped[list["Signature"]] = relationship(
        back_populates="waybill", cascade="all, delete-orphan", order_by="Signature.id"
    )

    @property
    def total(self) -> Decimal:
        return sum((line.price or Decimal(0) for line in self.lines), Decimal(0))

    def signature_of(self, role: SignerRole) -> "Signature | None":
        return next((s for s in self.signatures if s.signer_role == role), None)

    def __str__(self) -> str:
        return f"Накладная № {self.number} от {self.date:%d.%m.%Y}"


class WaybillLine(Base):
    """Строка накладной. Реквизиты позиции фиксируются на момент составления документа."""

    __tablename__ = "waybill_lines"
    __table_args__ = (UniqueConstraint("waybill_id", "item_id", name="uq_waybill_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    waybill_id: Mapped[int] = mapped_column(ForeignKey("waybills.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    name: Mapped[str] = mapped_column(String(500))
    inventory_number: Mapped[str | None] = mapped_column(String(100))
    serial_number: Mapped[str | None] = mapped_column(String(200))
    price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))

    waybill: Mapped[Waybill] = relationship(back_populates="lines")
    item: Mapped[Item] = relationship()


class Signature(Base):
    __tablename__ = "signatures"
    __table_args__ = (UniqueConstraint("waybill_id", "signer_role", name="uq_waybill_signer_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    waybill_id: Mapped[int] = mapped_column(ForeignKey("waybills.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    signer_role: Mapped[SignerRole] = mapped_column(_enum(SignerRole))
    provider: Mapped[str] = mapped_column(String(32))
    digest: Mapped[str] = mapped_column(String(64))  # SHA-256 канонического представления документа
    signature: Mapped[str] = mapped_column(Text)  # HMAC (простая ЭП) или CMS/CAdES в base64
    certificate: Mapped[str | None] = mapped_column(Text)  # сведения о сертификате ключа проверки ЭП
    signed_at: Mapped[datetime] = mapped_column(DateTime)

    waybill: Mapped[Waybill] = relationship(back_populates="signatures")
    user: Mapped[User] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User | None] = relationship()
