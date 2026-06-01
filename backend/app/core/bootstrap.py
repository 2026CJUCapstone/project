from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import database as db_models
from app.services import auth

SYSTEM_BOARD_IDS = {"__notice__", "__free__"}


def _nickname_is_available(db: Session, nickname: str, user_id: str | None = None) -> bool:
    query = db.query(db_models.User).filter(db_models.User.nickname == nickname)
    if user_id:
        query = query.filter(db_models.User.id != user_id)
    return query.first() is None


def ensure_admin_user(db: Session) -> db_models.User:
    admin = db.query(db_models.User).filter(db_models.User.username == settings.ADMIN_USERNAME).first()

    if admin is None:
        admin = db_models.User(
            username=settings.ADMIN_USERNAME,
            nickname=settings.ADMIN_NICKNAME
            if _nickname_is_available(db, settings.ADMIN_NICKNAME)
            else None,
            hashed_password=auth.get_password_hash(settings.ADMIN_PASSWORD or "admin1234"),
            role="admin",
        )
        db.add(admin)
        db.flush()
        return admin

    admin.role = "admin"
    if not admin.hashed_password and settings.ADMIN_PASSWORD:
        admin.hashed_password = auth.get_password_hash(settings.ADMIN_PASSWORD)
    if not admin.nickname and _nickname_is_available(db, settings.ADMIN_NICKNAME, admin.id):
        admin.nickname = settings.ADMIN_NICKNAME
    db.add(admin)
    db.flush()
    return admin


def ensure_system_boards(db: Session, admin: db_models.User) -> None:
    board_rows = {
        "__notice__": ("공지 게시판", "운영진 공지와 업데이트가 저장되는 시스템 게시판입니다."),
        "__free__": ("자유 게시판", "자유 주제 커뮤니티 글이 저장되는 시스템 게시판입니다."),
    }

    for board_id, (title, description) in board_rows.items():
        board = db.query(db_models.Problem).filter(db_models.Problem.id == board_id).first()
        if board is None:
            db.add(
                db_models.Problem(
                    id=board_id,
                    creator_id=admin.id,
                    title=title,
                    difficulty="iron5",
                    tags=["io"],
                    description=description,
                    test_cases={"sample": [], "hidden": []},
                    points=0,
                )
            )
            continue

        board.creator_id = admin.id
        board.title = title
        board.description = description
        board.points = 0
        db.add(board)


def bootstrap_application_data(db: Session) -> None:
    admin = ensure_admin_user(db)
    ensure_system_boards(db, admin)
    db.commit()
