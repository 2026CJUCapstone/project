from collections import Counter
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.core.database import get_db
from app.models import database as db_models
from app.models import schemas

router = APIRouter()


def _to_community_post(comment: db_models.Comment, user: db_models.User | None) -> schemas.CommunityPostRead:
    return schemas.CommunityPostRead(
        id=comment.id,
        problem_id=comment.problem_id,
        author=user.username if user else "unknown",
        avatar_url=user.avatar_url if user else None,
        content=comment.content,
        created_at=comment.created_at,
    )


@router.get("/posts", response_model=List[schemas.CommunityPostRead])
def list_posts(
    problem_id: str = Query(..., alias="problemId"),
    db: Session = Depends(get_db),
):
    comments = (
        db.query(db_models.Comment)
        .filter(db_models.Comment.problem_id == problem_id)
        .order_by(db_models.Comment.created_at.desc())
        .all()
    )

    user_ids = {comment.user_id for comment in comments}
    users = db.query(db_models.User).filter(db_models.User.id.in_(user_ids)).all() if user_ids else []
    users_by_id = {user.id: user for user in users}

    return [_to_community_post(comment, users_by_id.get(comment.user_id)) for comment in comments]


@router.post("/posts", response_model=schemas.CommunityPostRead)
def create_post(
    payload: schemas.CommunityPostCreate,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user),
):
    new_comment = db_models.Comment(
        problem_id=payload.problem_id,
        user_id=current_user.id,
        content=payload.content,
    )
    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)

    return _to_community_post(new_comment, current_user)


@router.delete("/posts/{post_id}", status_code=204)
def delete_post(
    post_id: str,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user),
):
    comment = db.query(db_models.Comment).filter(db_models.Comment.id == post_id).first()
    if comment is None:
        raise HTTPException(status_code=404, detail="Post not found")
    if comment.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only author can delete this post")

    db.delete(comment)
    db.commit()


@router.post("/posts/counts")
def get_post_counts(payload: schemas.CommunityPostCountsRequest, db: Session = Depends(get_db)):
    problem_ids = [item for item in payload.problem_ids if item]
    if not problem_ids:
        return {}

    comments = (
        db.query(db_models.Comment.problem_id)
        .filter(db_models.Comment.problem_id.in_(problem_ids))
        .all()
    )
    counts = Counter(problem_id for (problem_id,) in comments)

    return {problem_id: counts.get(problem_id, 0) for problem_id in problem_ids}
