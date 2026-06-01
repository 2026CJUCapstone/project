from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.routes.auth import require_admin
from app.core.database import get_db
from app.models import database as db_models
from app.models import schemas

router = APIRouter()


@router.get("/users", response_model=List[schemas.AdminUserRead])
def list_users(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(require_admin),
):
    return (
        db.query(db_models.User)
        .order_by(db_models.User.total_score.desc(), db_models.User.username.asc())
        .limit(limit)
        .all()
    )


@router.patch("/users/{user_id}", response_model=schemas.AdminUserRead)
def update_user(
    user_id: str,
    payload: schemas.AdminUserUpdate,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(require_admin),
):
    user = db.query(db_models.User).filter(db_models.User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.role is not None:
        if user.id == current_user.id and payload.role != "admin":
            raise HTTPException(status_code=400, detail="본인의 관리자 권한은 해제할 수 없습니다.")
        user.role = payload.role

    if payload.nickname is not None:
        nickname = payload.nickname.strip() or None
        if nickname:
            existing = (
                db.query(db_models.User)
                .filter(db_models.User.nickname == nickname, db_models.User.id != user.id)
                .first()
            )
            if existing:
                raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다.")
        user.nickname = nickname

    if payload.avatar_url is not None:
        user.avatar_url = payload.avatar_url.strip() or None

    db.add(user)
    db.commit()
    db.refresh(user)
    return user
