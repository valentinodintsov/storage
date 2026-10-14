"""Демонстрационные данные: python -m app.seed

Пароли демо-пользователей задаются переменной STORAGE_DEMO_PASSWORD (в .env), иначе генерируются
и выводятся в консоль.
"""

import os
import secrets
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app import models as m
from app.db import Base, SessionLocal, engine
from app.security import hash_password
from app.services.users import ensure_admin


def run() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        ensure_admin(db)
        if db.scalar(select(m.Organization).limit(1)):
            print("Данные уже есть — пропускаю.")
            return

        org = m.Organization(
            name="Государственное казённое учреждение «Центр информационных технологий»",
            short_name="ГКУ «ЦИТ»", inn="7736050003", kpp="773601001", ogrn="1027700132195",
            address="г. Москва, ул. Примерная, д. 1", head_name="Петров П. П.",
        )
        vendor = m.Counterparty(name="ООО «ТехноПоставка»", inn="7710489036", kpp="771001001",
                                contact_person="Сидоров С. С.", phone="+7 495 000-00-00", email="sales@example.ru")
        furniture_vendor = m.Counterparty(name="ООО «Офисная мебель»", inn="7702070139", kpp="770201001")
        db.add_all([org, vendor, furniture_vendor])
        db.flush()

        people = {
            "head": m.Employee(organization_id=org.id, last_name="Петров", first_name="Пётр", middle_name="Петрович",
                               position="Директор"),
            "manager": m.Employee(organization_id=org.id, last_name="Кузнецова", first_name="Анна",
                                  middle_name="Сергеевна", position="Заведующий складом", department="Хозяйственный отдел"),
            "user": m.Employee(organization_id=org.id, last_name="Иванов", first_name="Иван", middle_name="Иванович",
                               position="Ведущий специалист", department="Отдел сопровождения"),
            "user2": m.Employee(organization_id=org.id, last_name="Смирнова", first_name="Ольга",
                                middle_name="Викторовна", position="Бухгалтер", department="Бухгалтерия"),
        }
        db.add_all(people.values())
        db.flush()

        password = os.environ.get("STORAGE_DEMO_PASSWORD") or secrets.token_urlsafe(9)
        for login, role, key in (("manager", m.Role.MANAGER, "manager"), ("head", m.Role.HEAD, "head"),
                                 ("ivanov", m.Role.USER, "user"), ("smirnova", m.Role.USER, "user2")):
            db.add(m.User(username=login, role=role, employee_id=people[key].id, password_hash=hash_password(password)))

        cats = {name: m.Category(kind=kind, name=name) for kind, name in (
            (m.ItemKind.COMPUTER, "Системные блоки"), (m.ItemKind.COMPUTER, "Мониторы"),
            (m.ItemKind.COMPUTER, "Ноутбуки"), (m.ItemKind.LICENSE, "Операционные системы"),
            (m.ItemKind.LICENSE, "Офисное ПО"), (m.ItemKind.OFFICE, "МФУ и принтеры"),
            (m.ItemKind.FURNITURE, "Столы"), (m.ItemKind.FURNITURE, "Кресла"),
        )}
        db.add_all(cats.values())

        contract = m.Contract(
            number="0373200000126000123", date=date(2026, 3, 16), law=m.ContractLaw.FZ44,
            ikz="261773605000377360100100010010000244", subject="Поставка компьютерного оборудования и ПО",
            amount=Decimal("1850000.00"), organization_id=org.id, counterparty_id=vendor.id,
            valid_from=date(2026, 3, 16), valid_to=date(2026, 12, 31),
        )
        contract2 = m.Contract(
            number="15-М/2026", date=date(2026, 4, 2), law=m.ContractLaw.FZ44, subject="Поставка офисной мебели",
            amount=Decimal("420000.00"), organization_id=org.id, counterparty_id=furniture_vendor.id,
        )
        db.add_all([contract, contract2])
        db.flush()

        def item(kind, cat, name, inv, price, ctr, **kw):
            return m.Item(kind=kind, category_id=cats[cat].id, name=name, inventory_number=inv, price=Decimal(price),
                          organization_id=org.id, contract_id=ctr.id, counterparty_id=ctr.counterparty_id,
                          acquired_at=date(2026, 4, 10), **kw)

        db.add_all([
            item(m.ItemKind.COMPUTER, "Системные блоки", "Системный блок «Аквариус Pro P30»", "ВА-000101", "78500",
                 contract, serial_number="AQ30-551201", manufacturer="Аквариус", model="Pro P30", location="каб. 214"),
            item(m.ItemKind.COMPUTER, "Системные блоки", "Системный блок «Аквариус Pro P30»", "ВА-000102", "78500",
                 contract, serial_number="AQ30-551202", manufacturer="Аквариус", model="Pro P30"),
            item(m.ItemKind.COMPUTER, "Мониторы", "Монитор 27\" IRBIS SMARTVIEW", "ВА-000103", "24900", contract,
                 serial_number="IRB27-88310", manufacturer="IRBIS"),
            item(m.ItemKind.COMPUTER, "Ноутбуки", "Ноутбук YADRO KVADRA", "ВА-000104", "112000", contract,
                 serial_number="KV-2026-0042", manufacturer="YADRO"),
            item(m.ItemKind.LICENSE, "Операционные системы", "РЕД ОС, редакция «Рабочая станция»", "ЛИЦ-0001", "9800",
                 contract, manufacturer="РЕД СОФТ", license_key="RS-WS-2026-XXXX-0001", seats=10,
                 valid_until=date(2027, 4, 1)),
            item(m.ItemKind.LICENSE, "Офисное ПО", "МойОфис Стандартный", "ЛИЦ-0002", "7200", contract,
                 manufacturer="Новые облачные технологии", license_key="MO-STD-0002", seats=25),
            item(m.ItemKind.OFFICE, "МФУ и принтеры", "МФУ лазерное Pantum M7100DW", "ВА-000105", "31500", contract,
                 serial_number="PM71-77012", manufacturer="Pantum"),
            item(m.ItemKind.FURNITURE, "Столы", "Стол письменный 1400×700", "МБ-000201", "14300", contract2),
            item(m.ItemKind.FURNITURE, "Кресла", "Кресло офисное эргономичное", "МБ-000202", "18900", contract2),
        ])
        db.commit()
        print("Демо-данные созданы.")
        print(f"Пользователи manager, head, ivanov, smirnova — пароль: {password}")


if __name__ == "__main__":
    run()
