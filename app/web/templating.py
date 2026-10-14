from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import models
from app.config import settings

FLASH_COOKIE = "flash"

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


def _money(value) -> str:
    if value is None:
        return "—"
    value = Decimal(value)
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def _date(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return f"{value:%d.%m.%Y %H:%M}"
    if isinstance(value, date):
        return f"{value:%d.%m.%Y}"
    return str(value)


templates.env.filters["money"] = _money
templates.env.filters["ru_date"] = _date
templates.env.globals.update(
    app_name=settings.app_name,
    Role=models.Role,
    ROLE_LABELS=models.ROLE_LABELS,
    ITEM_KIND_LABELS=models.ITEM_KIND_LABELS,
    ITEM_STATUS_LABELS=models.ITEM_STATUS_LABELS,
    WAYBILL_TYPE_LABELS=models.WAYBILL_TYPE_LABELS,
    WAYBILL_STATUS_LABELS=models.WAYBILL_STATUS_LABELS,
    SIGNER_ROLE_LABELS=models.SIGNER_ROLE_LABELS,
    CONTRACT_LAW_LABELS=models.CONTRACT_LAW_LABELS,
    ItemStatus=models.ItemStatus,
    WaybillStatus=models.WaybillStatus,
    WaybillType=models.WaybillType,
    SignerRole=models.SignerRole,
)


def render(request: Request, name: str, user: models.User | None = None, status_code: int = 200, **context):
    flash = request.cookies.get(FLASH_COOKIE)
    if flash:
        level, _, text = unquote(flash).partition("|")
        flash = {"level": level, "text": text}
    context.update(user=user, flash=flash)
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def render_error(request: Request, status_code: int, message: str):
    return templates.TemplateResponse(
        request, "error.html", {"status_code": status_code, "message": message, "user": None, "flash": None},
        status_code=status_code,
    )


def redirect(url: str, message: str | None = None, level: str = "success") -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    if message:
        response.set_cookie(FLASH_COOKIE, quote(f"{level}|{message}"), max_age=60, httponly=True, samesite="lax")
    return response
