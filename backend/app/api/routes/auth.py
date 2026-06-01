import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import or_
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import check_rate_limit
from app.models import database as db_models
from app.models import schemas
from app.services import auth
from app.services import email as email_service

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _client_key(request: Request, purpose: str, identity: str = "") -> str:
    host = request.client.host if request.client else "unknown"
    return f"{purpose}:{host}:{identity.lower().strip()}"


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


RESET_REQUEST_MESSAGE = "계정이 확인되면 비밀번호 재설정 메일을 보냈습니다."


@router.post("/register")
def register(user: schemas.UserCreate, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(
        _client_key(request, "register", user.username),
        settings.AUTH_RATE_LIMIT_MAX_ATTEMPTS,
        settings.AUTH_RATE_LIMIT_WINDOW_SECONDS,
    )
    if db.query(db_models.User).filter(db_models.User.username == user.username).first():
        raise HTTPException(status_code=400, detail="이미 사용 중인 아이디입니다.")
    if db.query(db_models.User).filter(db_models.User.email == user.email).first():
        raise HTTPException(status_code=400, detail="이미 사용 중인 이메일입니다.")
    if user.nickname and db.query(db_models.User).filter(db_models.User.nickname == user.nickname).first():
        raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다.")

    hashed_pw = auth.get_password_hash(user.password)
    db_user = db_models.User(
        username=user.username,
        email=user.email,
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
    identity = user_data.username.strip()
    normalized_identity = identity.lower()
    # username, nickname 또는 email로 로그인 허용
    user = (
        db.query(db_models.User).filter(db_models.User.username == identity).first()
        or db.query(db_models.User).filter(db_models.User.nickname == identity).first()
        or db.query(db_models.User).filter(db_models.User.email == normalized_identity).first()
    )
    if not user or not auth.verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="아이디/닉네임/이메일 또는 비밀번호가 올바르지 않습니다.")

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

    if payload.email is not None:
        existing = (
            db.query(db_models.User)
            .filter(db_models.User.email == payload.email, db_models.User.id != current_user.id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="이미 사용 중인 이메일입니다.")
        current_user.email = payload.email

    if payload.avatar_url is not None:
        current_user.avatar_url = payload.avatar_url.strip() or None

    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/password-reset/request", response_model=schemas.PasswordResetResponse)
def request_password_reset(
    payload: schemas.PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    identity = payload.username_or_email.strip()
    normalized_identity = identity.lower()
    check_rate_limit(
        _client_key(request, "password-reset", normalized_identity),
        settings.AUTH_RATE_LIMIT_MAX_ATTEMPTS,
        settings.AUTH_RATE_LIMIT_WINDOW_SECONDS,
    )

    if settings.ENVIRONMENT == "production" and not email_service.is_email_configured():
        raise HTTPException(status_code=503, detail="비밀번호 재설정 메일 설정이 필요합니다.")

    user = (
        db.query(db_models.User)
        .filter(or_(db_models.User.username == identity, db_models.User.email == normalized_identity))
        .first()
    )
    if user is None or not user.email:
        return schemas.PasswordResetResponse(message=RESET_REQUEST_MESSAGE)

    now = _utc_now()
    token = secrets.token_urlsafe(48)
    db.query(db_models.PasswordResetToken).filter(
        db_models.PasswordResetToken.user_id == user.id,
        db_models.PasswordResetToken.used_at.is_(None),
    ).update({db_models.PasswordResetToken.used_at: now}, synchronize_session=False)
    db.add(
        db_models.PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_reset_token(token),
            expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
        )
    )
    db.commit()

    if email_service.is_email_configured():
        try:
            email_service.send_password_reset_email(user.email, token)
        except Exception as exc:
            db.query(db_models.PasswordResetToken).filter(
                db_models.PasswordResetToken.token_hash == _hash_reset_token(token),
                db_models.PasswordResetToken.used_at.is_(None),
            ).update({db_models.PasswordResetToken.used_at: _utc_now()}, synchronize_session=False)
            db.commit()
            raise HTTPException(status_code=503, detail="비밀번호 재설정 메일 전송에 실패했습니다.") from exc

    response = schemas.PasswordResetResponse(message=RESET_REQUEST_MESSAGE)
    if settings.ENVIRONMENT != "production":
        response.debug_reset_token = token
    return response


@router.post("/password-reset/confirm", response_model=schemas.PasswordResetResponse)
def confirm_password_reset(payload: schemas.PasswordResetConfirm, db: Session = Depends(get_db)):
    token_hash = _hash_reset_token(payload.token.strip())
    reset_token = (
        db.query(db_models.PasswordResetToken)
        .filter(
            db_models.PasswordResetToken.token_hash == token_hash,
            db_models.PasswordResetToken.used_at.is_(None),
        )
        .first()
    )
    now = _utc_now()
    if reset_token is None:
        raise HTTPException(status_code=400, detail="재설정 토큰이 올바르지 않거나 이미 사용되었습니다.")
    if _as_utc(reset_token.expires_at) < now:
        reset_token.used_at = now
        db.add(reset_token)
        db.commit()
        raise HTTPException(status_code=400, detail="재설정 토큰이 만료되었습니다.")

    user = db.query(db_models.User).filter(db_models.User.id == reset_token.user_id).first()
    if user is None:
        reset_token.used_at = now
        db.add(reset_token)
        db.commit()
        raise HTTPException(status_code=400, detail="재설정 토큰이 올바르지 않거나 이미 사용되었습니다.")

    user.hashed_password = auth.get_password_hash(payload.new_password)
    reset_token.used_at = now
    db.add(user)
    db.add(reset_token)
    db.commit()
    return schemas.PasswordResetResponse(message="비밀번호가 변경되었습니다.")


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
