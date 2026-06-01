from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import check_rate_limit
from app.models import database as db_models
from app.models import schemas
from app.services import auth

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _client_key(request: Request, purpose: str, identity: str = "") -> str:
    host = request.client.host if request.client else "unknown"
    return f"{purpose}:{host}:{identity.lower().strip()}"


@router.post("/register")
def register(user: schemas.UserCreate, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(
        _client_key(request, "register", user.username),
        settings.AUTH_RATE_LIMIT_MAX_ATTEMPTS,
        settings.AUTH_RATE_LIMIT_WINDOW_SECONDS,
    )
    if db.query(db_models.User).filter(db_models.User.username == user.username).first():
        raise HTTPException(status_code=400, detail="이미 사용 중인 아이디입니다.")
    if user.nickname and db.query(db_models.User).filter(db_models.User.nickname == user.nickname).first():
        raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다.")

    hashed_pw = auth.get_password_hash(user.password)
    db_user = db_models.User(
        username=user.username,
        nickname=user.nickname,
        hashed_password=hashed_pw,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return {"message": "User created successfully"}

@router.post("/login", response_model=schemas.Token)
def login(user_data: schemas.UserLogin, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(
        _client_key(request, "login", user_data.username),
        settings.AUTH_RATE_LIMIT_MAX_ATTEMPTS,
        settings.AUTH_RATE_LIMIT_WINDOW_SECONDS,
    )
    # username 또는 nickname으로 로그인 허용
    user = (
        db.query(db_models.User).filter(db_models.User.username == user_data.username).first()
        or db.query(db_models.User).filter(db_models.User.nickname == user_data.username).first()
    )
    if not user or not auth.verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="아이디/닉네임 또는 비밀번호가 올바르지 않습니다.")

    access_token = auth.create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, auth.get_secret_key(), algorithms=[auth.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")

    user = db.query(db_models.User).filter(db_models.User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/me", response_model=schemas.UserRead)
def read_me(current_user: db_models.User = Depends(get_current_user)):
    return current_user


@router.get("/profile", response_model=schemas.UserRead)
def read_profile(current_user: db_models.User = Depends(get_current_user)):
    return current_user


@router.patch("/profile", response_model=schemas.UserRead)
def update_profile(
    payload: schemas.UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user),
):
    if payload.nickname is not None:
        nickname = payload.nickname.strip() or None
        if nickname:
            existing = (
                db.query(db_models.User)
                .filter(db_models.User.nickname == nickname, db_models.User.id != current_user.id)
                .first()
            )
            if existing:
                raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다.")
        current_user.nickname = nickname

    if payload.avatar_url is not None:
        current_user.avatar_url = payload.avatar_url.strip() or None

    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user


def require_admin(current_user: db_models.User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자 권한이 필요합니다.")
    return current_user


def get_optional_current_user(token: str | None = Depends(optional_oauth2_scheme), db: Session = Depends(get_db)):
    if not token:
        return None

    try:
        payload = jwt.decode(token, auth.get_secret_key(), algorithms=[auth.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None

    return db.query(db_models.User).filter(db_models.User.username == username).first()
