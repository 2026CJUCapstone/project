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

# 주소: /api/v1/problems/leaderboard
@router.get("/leaderboard", response_model=List[schemas.LeaderboardRead])
def get_leaderboard(db: Session = Depends(get_db)):
    return db.query(db_models.User).order_by(db_models.User.total_score.desc()).limit(50).all()
