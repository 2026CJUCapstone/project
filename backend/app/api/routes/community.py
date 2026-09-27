from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user, get_optional_current_user
from app.core.bootstrap import SYSTEM_BOARD_IDS
from app.core.database import get_db
from app.models import database as db_models
from app.models import schemas
from app.services.contest_access import require_public_problem, private_problem_ids
from app.services.public_identity import public_display_name, public_problem_id, public_receipt_id

router = APIRouter()


NOTICE_BOARD_ID = "__notice__"


def _is_admin(user: db_models.User | None) -> bool:
    return user is not None and user.role == "admin"


def _to_community_post(
    comment: db_models.Comment,
    user: db_models.User | None,
    current_user: db_models.User | None = None,
    problem: db_models.Problem | None = None,
) -> schemas.CommunityPostRead:
    privileged = current_user is not None and (
        current_user.role == "admin" or comment.user_id == current_user.id
    )
    return schemas.CommunityPostRead(
        id=comment.id if privileged else public_receipt_id(comment.id),
        problem_id=comment.problem_id if comment.problem_id in SYSTEM_BOARD_IDS else (
            public_problem_id(problem) if problem is not None else comment.problem_id
        ),
        user_id=comment.user_id if privileged else None,
        author=public_display_name(user),
        avatar_url=user.avatar_url if user else None,
        content=comment.content,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        can_delete=current_user is not None and (comment.user_id == current_user.id or _is_admin(current_user)),
        can_edit=current_user is not None and (comment.user_id == current_user.id or _is_admin(current_user)),
    )


@router.get("/posts", response_model=List[schemas.CommunityPostRead])
def list_posts(
    problem_id: str = Query(..., alias="problemId"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user),
):
    if problem_id not in SYSTEM_BOARD_IDS:
        problem = require_public_problem(db, problem_id, current_user)
        problem_id = problem.id
    comments = (
        db.query(db_models.Comment)
        .filter(db_models.Comment.problem_id == problem_id)
        .order_by(db_models.Comment.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    user_ids = {comment.user_id for comment in comments}
    users = db.query(db_models.User).filter(db_models.User.id.in_(user_ids)).all() if user_ids else []
    users_by_id = {user.id: user for user in users}

    return [
        _to_community_post(comment, users_by_id.get(comment.user_id), current_user, problem if problem_id not in SYSTEM_BOARD_IDS else None)
        for comment in comments
    ]


@router.post("/posts", response_model=schemas.CommunityPostRead)
def create_post(
    payload: schemas.CommunityPostCreate,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user),
):
    internal_problem_id = payload.problem_id
    problem = None
    if payload.problem_id not in SYSTEM_BOARD_IDS:
        problem = require_public_problem(db, payload.problem_id, current_user)
        internal_problem_id = problem.id
    if internal_problem_id == NOTICE_BOARD_ID and not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="공지 작성은 관리자만 가능합니다.")

    if internal_problem_id not in SYSTEM_BOARD_IDS:
        exists = db.query(db_models.Problem.id).filter(db_models.Problem.id == internal_problem_id).first()
        if exists is None:
            raise HTTPException(status_code=404, detail="Problem not found")

    new_comment = db_models.Comment(
        problem_id=internal_problem_id,
        user_id=current_user.id,
        content=payload.content,
    )
    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)

    return _to_community_post(new_comment, current_user, current_user, problem)


@router.delete("/posts/{post_id}", status_code=204)
def delete_post(
    post_id: str,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user),
):
    comment = db.query(db_models.Comment).filter(db_models.Comment.id == post_id).first()
    if comment is None:
        raise HTTPException(status_code=404, detail="Post not found")
    require_public_problem(db, comment.problem_id, current_user)
    if comment.user_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Only author or admin can delete this post")

    db.delete(comment)
    db.commit()


@router.patch("/posts/{post_id}", response_model=schemas.CommunityPostRead)
def update_post(
    post_id: str,
    payload: schemas.CommunityPostUpdate,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user),
):
    comment = db.query(db_models.Comment).filter(db_models.Comment.id == post_id).first()
    if comment is None:
        raise HTTPException(status_code=404, detail="Post not found")
    require_public_problem(db, comment.problem_id, current_user)
    if comment.user_id != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Only author or admin can edit this post")

    comment.content = payload.content
    db.add(comment)
    db.commit()
    db.refresh(comment)
    user = db.query(db_models.User).filter(db_models.User.id == comment.user_id).first()
    problem = db.get(db_models.Problem, comment.problem_id) if comment.problem_id not in SYSTEM_BOARD_IDS else None
    return _to_community_post(comment, user, current_user, problem)


@router.post("/posts/counts")
def get_post_counts(payload: schemas.CommunityPostCountsRequest, db: Session = Depends(get_db)):
    requested_ids = [item for item in payload.problem_ids if item]
    public_rows = db.query(db_models.Problem.id, db_models.Problem.public_id).filter(
        or_(
            db_models.Problem.id.in_(requested_ids),
            db_models.Problem.public_id.in_(requested_ids),
        )
    ).all()
    public_to_internal = {public_id: internal_id for internal_id, public_id in public_rows}
    internal_to_public = {internal_id: public_id for internal_id, public_id in public_rows}
    requested_to_internal = {
        item: public_to_internal.get(item, item) for item in requested_ids
    }
    problem_ids = list(dict.fromkeys(requested_to_internal.values()))
    hidden_ids = set(db.scalars(private_problem_ids()).all())
    hidden_ids.update(problem_id for (problem_id,) in db.query(db_models.Problem.id).filter(
        db_models.Problem.id.in_(problem_ids), db_models.Problem.deleted_at.is_not(None)).all())
    problem_ids = [item for item in problem_ids if item not in hidden_ids]
    if not problem_ids:
        return {}

    counts = dict(
        db.query(db_models.Comment.problem_id, func.count(db_models.Comment.id))
        .filter(db_models.Comment.problem_id.in_(problem_ids))
        .group_by(db_models.Comment.problem_id)
        .all()
    )

    return {
        internal_to_public.get(internal, requested): counts.get(internal, 0)
        for requested, internal in requested_to_internal.items()
        if internal not in hidden_ids
    }
