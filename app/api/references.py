from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import CAN_EDIT_ASSETS, CAN_VIEW_ALL, require_roles
from app.services import crud

router = APIRouter()


def _register(ref: crud.Reference) -> None:
    """Регистрирует типизированные CRUD-эндпоинты справочника (для корректной схемы OpenAPI)."""
    In, Out = ref.schema_in, ref.schema_out
    base = f"/{ref.slug}"
    tags = [ref.title]

    @router.get(base, response_model=list[Out], tags=tags, summary=f"{ref.title}: список")
    def list_(q: str | None = None, limit: int = 100, offset: int = 0, db: Session = Depends(get_db),
              _: User = Depends(require_roles(*CAN_VIEW_ALL))):
        return crud.list_entities(db, ref, q, min(limit, 500), offset)

    @router.get(base + "/{entity_id}", response_model=Out, tags=tags, summary=f"{ref.title}: карточка")
    def get(entity_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles(*CAN_VIEW_ALL))):
        return crud.get_entity(db, ref.model, entity_id)

    @router.post(base, response_model=Out, status_code=201, tags=tags, summary=f"{ref.title}: создать")
    def create(payload: In, db: Session = Depends(get_db),  # type: ignore[valid-type]
               user: User = Depends(require_roles(*CAN_EDIT_ASSETS))):
        return crud.create_entity(db, user, ref.model, payload)

    @router.put(base + "/{entity_id}", response_model=Out, tags=tags, summary=f"{ref.title}: изменить")
    def update(entity_id: int, payload: In, db: Session = Depends(get_db),  # type: ignore[valid-type]
               user: User = Depends(require_roles(*CAN_EDIT_ASSETS))):
        return crud.update_entity(db, user, crud.get_entity(db, ref.model, entity_id), payload)

    @router.delete(base + "/{entity_id}", status_code=204, tags=tags, summary=f"{ref.title}: удалить")
    def delete(entity_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*CAN_EDIT_ASSETS))):
        crud.delete_entity(db, user, crud.get_entity(db, ref.model, entity_id))


for _ref in crud.REFERENCES.values():
    _register(_ref)
