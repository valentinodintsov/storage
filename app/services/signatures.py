"""Электронная подпись документов.

Подписывается каноническое представление накладной (JSON с отсортированными ключами);
в подписи сохраняется SHA-256 этого представления, что позволяет обнаружить любое изменение
документа после подписания.
"""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime

from app.config import settings
from app.errors import ServiceError
from app.models import Signature, SignerRole, User, Waybill
from app.schemas import SignIn
from app.security import verify_password


def canonical_content(waybill: Waybill) -> bytes:
    data = {
        "number": waybill.number,
        "date": waybill.date.isoformat(),
        "type": waybill.type.value,
        "organization": {"id": waybill.organization_id, "inn": waybill.organization.inn},
        "sender": {"id": waybill.sender_id, "name": waybill.sender.full_name},
        "receiver": {"id": waybill.receiver_id, "name": waybill.receiver.full_name},
        "basis": waybill.basis,
        "lines": [
            {
                "item_id": line.item_id,
                "name": line.name,
                "inventory_number": line.inventory_number,
                "serial_number": line.serial_number,
                "price": str(line.price) if line.price is not None else None,
            }
            for line in waybill.lines
        ],
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest_of(waybill: Waybill) -> str:
    return hashlib.sha256(canonical_content(waybill)).hexdigest()


@dataclass
class SignResult:
    signature: str
    certificate: str | None


class SimpleProvider:
    """Простая электронная подпись (63-ФЗ, ст. 5 ч. 2): подтверждение личности входом в систему.

    Сервер фиксирует факт подписания HMAC-кодом, привязанным к пользователю, документу и времени.
    """

    name = "simple"

    def _mac(self, user_id: int, role: SignerRole, digest: str, signed_at: datetime) -> str:
        message = f"{user_id}|{role.value}|{digest}|{signed_at.isoformat()}".encode()
        return hmac.new(settings.secret_key.get_secret_value().encode(), message, hashlib.sha256).hexdigest()

    def sign(self, user: User, role: SignerRole, digest: str, signed_at: datetime, data: SignIn) -> SignResult:
        if not data.password or not verify_password(data.password, user.password_hash):
            raise ServiceError("Для подписания простой ЭП введите действующий пароль")
        return SignResult(
            signature=self._mac(user.id, role, digest, signed_at),
            certificate=f"ПЭП: {user.display_name} (учётная запись {user.username})",
        )

    def verify(self, sig: Signature) -> bool | None:
        expected = self._mac(sig.user_id, sig.signer_role, sig.digest, sig.signed_at)
        return hmac.compare_digest(expected, sig.signature)


class CadesProvider:
    """Усиленная ЭП в формате CAdES-BES (откреплённая).

    Подпись формируется на рабочем месте пользователя через КриптоПро ЭЦП Browser plug-in
    (см. static/signature.js) и передаётся на сервер в base64. Криптографическая проверка
    ГОСТ-подписи выполняется внешним сервисом (КриптоПро DSS/SVS и т.п.) — точка интеграции verify().
    """

    name = "cades"

    def sign(self, user: User, role: SignerRole, digest: str, signed_at: datetime, data: SignIn) -> SignResult:
        if not data.signature:
            raise ServiceError("Не передана электронная подпись документа")
        try:
            raw = base64.b64decode(data.signature, validate=True)
        except ValueError:
            raise ServiceError("Подпись должна быть в кодировке base64")
        if not raw or raw[0] != 0x30:  # ASN.1 SEQUENCE — начало структуры CMS
            raise ServiceError("Переданные данные не являются подписью CMS")
        return SignResult(signature=data.signature, certificate=data.certificate)

    def verify(self, sig: Signature) -> bool | None:
        return None  # требуется внешний сервис проверки


PROVIDERS = {p.name: p for p in (SimpleProvider(), CadesProvider())}


def provider_for(role: SignerRole):
    # Подтверждение получения сотрудником — всегда простая ЭП; подписи МОЛ и руководителя — настраиваемый провайдер
    name = "simple" if role == SignerRole.RECEIVER else settings.signature_provider
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ServiceError(f"Неизвестный провайдер ЭП: {name}")


def make_signature(user: User, role: SignerRole, waybill: Waybill, data: SignIn) -> Signature:
    provider = provider_for(role)
    digest = digest_of(waybill)
    signed_at = datetime.now().replace(microsecond=0)
    result = provider.sign(user, role, digest, signed_at, data)
    return Signature(
        user_id=user.id,
        signer_role=role,
        provider=provider.name,
        digest=digest,
        signature=result.signature,
        certificate=result.certificate,
        signed_at=signed_at,
    )


def verify_signature(waybill: Waybill, sig: Signature) -> bool | None:
    """True — подпись верна и документ не изменён; False — нарушена; None — нужна внешняя проверка."""
    if sig.digest != digest_of(waybill):
        return False
    provider = PROVIDERS.get(sig.provider)
    return provider.verify(sig) if provider else None
