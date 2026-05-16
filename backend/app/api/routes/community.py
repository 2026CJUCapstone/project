from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.models import database as db_models
from app.models import schemas
from app.api.routes.auth import get_current_user

router = APIRouter()

@router.post("/{problem_id}/comments", response_model=schemas.CommentRead)
def create_comment(
    problem_id: str,
    comment: schemas.CommentCreate,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    problem = db.query(db_models.Problem).filter(db_models.Problem.id == problem_id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")

    new_comment = db_models.Comment(
        problem_id=problem_id,
        user_id=current_user.id,
        content=comment.content
    )
    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)
    return new_comment

@router.get("/{problem_id}/comments", response_model=List[schemas.CommentRead])
def list_comments(problem_id: str, db: Session = Depends(get_db)):
    return db.query(db_models.Comment).filter(db_models.Comment.problem_id == problem_id).order_by(db_models.Comment.created_at.desc()).all()
