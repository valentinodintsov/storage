from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Item, ItemKind, ItemStatus, User
from app.schemas import ItemIn, ItemOut, ItemStatusIn
from app.security import CAN_EDIT_ASSETS, CAN_VIEW_ALL, get_current_user, require_roles
from app.services import items as svc

router = APIRouter(prefix="/items", tags=["Учётные позиции"])


@router.get("", response_model=list[ItemOut], summary="Список (пользователь видит только своё)")
def list_items(kind: ItemKind | None = None, status: ItemStatus | None = None, holder_id: int | None = None,
               organization_id: int | None = None, contract_id: int | None = None, q: str | None = None,
               limit: int = 100, offset: int = 0,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_items(db, user, kind=kind, status=status, holder_id=holder_id, organization_id=organization_id,
                          contract_id=contract_id, q=q, limit=min(limit, 500), offset=offset)


@router.get("/summary", summary="Сводка по видам учёта и статусам")
def summary(db: Session = Depends(get_db), _: User = Depends(require_roles(*CAN_VIEW_ALL))):
    rows = db.execute(
        select(Item.kind, Item.status, func.count(), func.coalesce(func.sum(Item.price), 0))
        .group_by(Item.kind, Item.status)
    )
    return [{"kind": k, "status": s, "count": c, "amount": a} for k, s, c, a in rows]


@router.get("/{item_id}", response_model=ItemOut)
def get_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.get_item(db, user, item_id)


@router.post("", response_model=ItemOut, status_code=201)
def create_item(payload: ItemIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*CAN_EDIT_ASSETS))):
    return svc.create_item(db, user, payload)


@router.put("/{item_id}", response_model=ItemOut)
def update_item(item_id: int, payload: ItemIn, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*CAN_EDIT_ASSETS))):
    return svc.update_item(db, user, svc.get_item(db, user, item_id), payload)


@router.post("/{item_id}/status", response_model=ItemOut, summary="Ремонт / возврат из ремонта / списание")
def change_status(item_id: int, payload: ItemStatusIn, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(*CAN_EDIT_ASSETS))):
    return svc.change_status(db, user, svc.get_item(db, user, item_id), payload)


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*CAN_EDIT_ASSETS))):
    svc.delete_item(db, user, svc.get_item(db, user, item_id))
