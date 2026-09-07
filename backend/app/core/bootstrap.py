import secrets

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import database as db_models
from app.services import auth

SYSTEM_BOARD_IDS = {"__notice__", "__free__"}
COMMUNITY_GUIDE_NOTICE_ID = "system-community-guide-v1"
COMMUNITY_GUIDE_NOTICE = """# B++ 커뮤니티 이용 안내

B++ 커뮤니티는 코드를 배우고 문제를 해결하는 과정에서 얻은 지식을 함께 나누는 공간입니다.

## 게시판은 이렇게 이용하세요

- **공지**: 서비스 운영, 업데이트, 이용 안내를 확인합니다. 공지는 관리자만 작성할 수 있습니다.
- **문제 토론**: 각 챌린지의 아이디어, 막힌 부분, 풀이 방향을 나눕니다. 문제 목록에서 원하는 문제를 선택해 들어갈 수 있습니다.
- **자유 게시판**: B++ 문법, 알고리즘, 컴파일러, 개선 제안 등 프로그래밍과 관련된 이야기를 자유롭게 나눕니다.

## 함께 지켜주세요

1. 질문할 때는 시도한 코드와 예상한 결과, 실제 결과를 함께 적어주세요.
2. 정답 코드를 그대로 공개하기보다 핵심 아이디어와 힌트를 중심으로 설명해주세요.
3. 다른 사용자를 존중하고 비방, 도배, 광고, 개인정보 공유는 삼가주세요.
4. 작성한 글은 본인과 관리자가 수정하거나 삭제할 수 있습니다.

처음 방문했다면 **IDE에서 기본 예제를 실행**해보고, **챌린지에 도전**한 뒤 막힌 부분을 문제 토론에 남겨보세요. 함께 배우는 기록이 다음 사용자에게도 좋은 길잡이가 됩니다.
"""


def _nickname_is_available(db: Session, nickname: str, user_id: str | None = None) -> bool:
    query = db.query(db_models.User).filter(db_models.User.nickname == nickname)
    if user_id:
        query = query.filter(db_models.User.id != user_id)
    return query.first() is None


def ensure_admin_user(db: Session) -> db_models.User:
    admin = db.query(db_models.User).filter(db_models.User.username == settings.ADMIN_USERNAME).first()
    admin_password = settings.ADMIN_PASSWORD

    if admin is None:
        admin = db_models.User(
            username=settings.ADMIN_USERNAME,
            nickname=settings.ADMIN_NICKNAME
            if _nickname_is_available(db, settings.ADMIN_NICKNAME)
            else None,
            hashed_password=auth.get_password_hash(admin_password or secrets.token_urlsafe(32)),
            role="admin",
        )
        db.add(admin)
        db.flush()
        return admin

    admin.role = "admin"
    if admin_password:
        admin.hashed_password = auth.get_password_hash(admin_password)
    elif not admin.hashed_password or auth.verify_password("admin1234", admin.hashed_password):
        admin.hashed_password = auth.get_password_hash(secrets.token_urlsafe(32))
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


def ensure_community_guide_notice(db: Session, admin: db_models.User) -> None:
    notice = db.query(db_models.Comment).filter(db_models.Comment.id == COMMUNITY_GUIDE_NOTICE_ID).first()
    if notice is None:
        db.add(
            db_models.Comment(
                id=COMMUNITY_GUIDE_NOTICE_ID,
                problem_id="__notice__",
                user_id=admin.id,
                content=COMMUNITY_GUIDE_NOTICE,
            )
        )
        return

    notice.problem_id = "__notice__"
    notice.user_id = admin.id
    notice.content = COMMUNITY_GUIDE_NOTICE
    db.add(notice)


def bootstrap_application_data(db: Session) -> None:
    admin = ensure_admin_user(db)
    ensure_system_boards(db, admin)
    ensure_community_guide_notice(db, admin)
    db.commit()
