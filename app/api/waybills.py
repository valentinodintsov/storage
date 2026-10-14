import base64

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, WaybillStatus, WaybillType
from app.schemas import ReasonIn, SignDocument, SignIn, WaybillIn, WaybillOut
from app.security import CAN_EDIT_ASSETS, get_current_user, require_roles
from app.services import signatures
from app.services import waybills as svc

router = APIRouter(prefix="/waybills", tags=["Накладные"])


@router.get("", response_model=list[WaybillOut])
def list_waybills(status: WaybillStatus | None = None, type: WaybillType | None = None,
                  employee_id: int | None = None, limit: int = 100, offset: int = 0,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_waybills(db, user, status=status, type_=type, employee_id=employee_id,
                             limit=min(limit, 500), offset=offset)


@router.get("/{waybill_id}", response_model=WaybillOut)
def get_waybill(waybill_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.get_waybill(db, user, waybill_id)


@router.post("", response_model=WaybillOut, status_code=201)
def create_waybill(payload: WaybillIn, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(*CAN_EDIT_ASSETS))):
    return svc.create_waybill(db, user, payload)


@router.put("/{waybill_id}", response_model=WaybillOut)
def update_waybill(waybill_id: int, payload: WaybillIn, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(*CAN_EDIT_ASSETS))):
    return svc.update_waybill(db, user, svc.get_waybill(db, user, waybill_id), payload)


@router.delete("/{waybill_id}", status_code=204,
               summary="Удалить: черновик без подписей; администратор — любую накладную с указанием причины")
def delete_waybill(waybill_id: int, reason: str = "", db: Session = Depends(get_db),
                   user: User = Depends(require_roles(*CAN_EDIT_ASSETS))):
    svc.delete_waybill(db, user, svc.get_waybill(db, user, waybill_id), reason)


@router.get("/{waybill_id}/sign-document", response_model=SignDocument,
            summary="Данные для формирования ЭП на стороне клиента")
def sign_document(waybill_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    waybill = svc.get_waybill(db, user, waybill_id)
    role = svc.next_signer_role(user, waybill)
    return SignDocument(
        digest=signatures.digest_of(waybill),
        content_base64=base64.b64encode(signatures.canonical_content(waybill)).decode(),
        provider=signatures.provider_for(role).name if role else "",
    )


@router.post("/{waybill_id}/sign", response_model=WaybillOut,
             summary="Подписать: МОЛ → руководитель → получатель (по статусу и роли)")
def sign(waybill_id: int, payload: SignIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.sign_waybill(db, user, svc.get_waybill(db, user, waybill_id), payload)


@router.post("/{waybill_id}/signatures/{signature_id}/revoke", response_model=WaybillOut,
             summary="Отменить подпись: свою последнюю; администратор — любую (вместе с последующими)")
def revoke_signature(waybill_id: int, signature_id: int, payload: ReasonIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.revoke_signature(db, user, svc.get_waybill(db, user, waybill_id), signature_id, payload.reason)


@router.post("/{waybill_id}/cancel", response_model=WaybillOut)
def cancel(waybill_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*CAN_EDIT_ASSETS))):
    return svc.cancel_waybill(db, user, svc.get_waybill(db, user, waybill_id))
