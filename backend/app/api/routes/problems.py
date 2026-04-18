from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.models import database as db_models
from app.models import schemas

router = APIRouter()

@router.post("/", response_model=schemas.ProblemRead, include_in_schema=False)
@router.post("", response_model=schemas.ProblemRead)
def create_problem(problem: schemas.ProblemCreate, db: Session = Depends(get_db)):
    db_problem = db_models.Problem(
        title=problem.title,
        difficulty=problem.difficulty,
        tags=problem.tags,
        description=problem.description,
        test_cases=[tc.model_dump(by_alias=True) for tc in problem.test_cases]
    )
    db.add(db_problem)
    db.commit()
    db.refresh(db_problem)
    return db_problem

@router.get("/", response_model=List[schemas.ProblemRead], include_in_schema=False)
@router.get("", response_model=List[schemas.ProblemRead])
def list_problems(
    difficulty: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(db_models.Problem)
    
    if difficulty:
        query = query.filter(db_models.Problem.difficulty == difficulty)
    
    problems = query.all()
    
    if tag:
        problems = [p for p in problems if tag in p.tags]
            
    return problems


def _leaderboard_entry(user: db_models.User, rank: int) -> dict:
    return {
        "rank": rank,
        "username": user.username,
        "total_score": user.total_score,
        "avatar_url": user.avatar_url,
    }


def _leaderboard_rank(db: Session, user_id: str) -> int:
    ordered_users = (
        db.query(db_models.User)
        .order_by(db_models.User.total_score.desc(), db_models.User.username.asc())
        .all()
    )
    return next((index for index, current in enumerate(ordered_users, start=1) if current.id == user_id), 1)


# 주소: /api/v1/problems/leaderboard
@router.get("/leaderboard", response_model=List[schemas.LeaderboardRead])
def get_leaderboard(
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    users = (
        db.query(db_models.User)
        .order_by(db_models.User.total_score.desc(), db_models.User.username.asc())
        .limit(limit)
        .all()
    )
    return [_leaderboard_entry(user, rank) for rank, user in enumerate(users, start=1)]


@router.post("/leaderboard/score", response_model=schemas.LeaderboardScoreRead)
def submit_leaderboard_score(
    score: schemas.LeaderboardScoreCreate,
    db: Session = Depends(get_db),
):
    username = score.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    user = db.query(db_models.User).filter(db_models.User.username == username).first()
    if user is None:
        user = db_models.User(
            username=username,
            total_score=0,
            avatar_url=score.avatar_url,
        )
        db.add(user)
        db.flush()
    else:
        if score.avatar_url:
            user.avatar_url = score.avatar_url

    existing_score = (
        db.query(db_models.UserProblemScore)
        .filter(
            db_models.UserProblemScore.user_id == user.id,
            db_models.UserProblemScore.challenge_id == score.challenge_id,
        )
        .first()
    )

    awarded_points = 0
    already_solved = existing_score is not None
    if existing_score is None:
        awarded_points = score.points
        user.total_score += awarded_points
        db.add(
            db_models.UserProblemScore(
                user_id=user.id,
                challenge_id=score.challenge_id,
                points_awarded=awarded_points,
            )
        )

    db.commit()
    db.refresh(user)

    return {
        **_leaderboard_entry(user, _leaderboard_rank(db, user.id)),
        "challenge_id": score.challenge_id,
        "awarded_points": awarded_points,
        "already_solved": already_solved,
    }


@router.put("/{id}", response_model=schemas.ProblemRead)
def update_problem(id: str, problem: schemas.ProblemCreate, db: Session = Depends(get_db)):
    db_problem = db.query(db_models.Problem).filter(db_models.Problem.id == id).first()
    if not db_problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    
    db_problem.title = problem.title
    db_problem.difficulty = problem.difficulty
    db_problem.tags = problem.tags
    db_problem.description = problem.description
    db_problem.test_cases = [tc.model_dump(by_alias=True) for tc in problem.test_cases]
    
    db.commit()
    db.refresh(db_problem)
    return db_problem

@router.delete("/{id}")
def delete_problem(id: str, db: Session = Depends(get_db)):
    db_problem = db.query(db_models.Problem).filter(db_models.Problem.id == id).first()
    if not db_problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    db.delete(db_problem)
    db.commit()
    return {"message": "Successfully deleted"}
