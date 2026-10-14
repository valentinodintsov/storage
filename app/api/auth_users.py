from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import NotAuthenticated
from app.models import Role, User
from app.schemas import Token, UserIn, UserOut
from app.security import authenticate, create_token, get_current_user, require_roles
from app.services import crud
from app.services import users as svc

router = APIRouter()


@router.post("/auth/token", response_model=Token, tags=["Авторизация"])
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate(db, form.username, form.password)
    if not user:
        raise NotAuthenticated("Неверный логин или пароль")
    return Token(access_token=create_token(user))


@router.get("/auth/me", response_model=UserOut, tags=["Авторизация"])
def me(user: User = Depends(get_current_user)):
    return user


admin_only = require_roles(Role.ADMIN)


@router.get("/users", response_model=list[UserOut], tags=["Пользователи"])
def list_users(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return svc.list_users(db)


@router.post("/users", response_model=UserOut, status_code=201, tags=["Пользователи"])
def create_user(payload: UserIn, db: Session = Depends(get_db), actor: User = Depends(admin_only)):
    return svc.create_user(db, actor, payload)


@router.put("/users/{user_id}", response_model=UserOut, tags=["Пользователи"])
def update_user(user_id: int, payload: UserIn, db: Session = Depends(get_db), actor: User = Depends(admin_only)):
    return svc.update_user(db, actor, crud.get_entity(db, User, user_id), payload)
