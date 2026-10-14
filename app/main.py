from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import api, models  # noqa: F401 — регистрация моделей
from app.config import settings
from app.db import Base, SessionLocal, engine
from app.errors import NotAuthenticated, ServiceError
from app.services.users import ensure_admin
from app.web import routes as web
from app.web.templating import FLASH_COOKIE, render_error


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        ensure_admin(db)
    yield


app = FastAPI(
    title=f"{settings.app_name} — учёт имущества",
    description="Учёт компьютерной техники, лицензий ПО, оргтехники и мебели; накладные с электронной подписью.",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(api.router)
app.include_router(web.router)


def _is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError):
    if _is_api(request):
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, NotAuthenticated) else None
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code, headers=headers)
    if isinstance(exc, NotAuthenticated):
        return RedirectResponse(f"/login?next={quote(str(request.url.path))}", status_code=303)
    return render_error(request, exc.status_code, exc.message)


@app.middleware("http")
async def clear_flash(request: Request, call_next):
    """Сообщение-уведомление показывается один раз: удаляем cookie после отрисовки страницы."""
    response = await call_next(request)
    if FLASH_COOKIE in request.cookies and response.status_code < 300 and response.headers.get(
        "content-type", ""
    ).startswith("text/html"):
        response.delete_cookie(FLASH_COOKIE)
    return response


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
