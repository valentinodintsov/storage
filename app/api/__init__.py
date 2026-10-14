from fastapi import APIRouter

from app.api import auth_users, items, references, waybills

router = APIRouter(prefix="/api/v1")
router.include_router(auth_users.router)
router.include_router(references.router, prefix="/refs")
router.include_router(items.router)
router.include_router(waybills.router)
