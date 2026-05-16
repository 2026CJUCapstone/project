from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.models import database as db_models
from app.models import schemas
from app.api.routes.auth import get_current_user
from app.services.compiler import compiler_instance

router = APIRouter()

@router.post("/", response_model=schemas.ProblemRead)
def create_problem(
    problem: schemas.ProblemCreate,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    db_problem = db_models.Problem(
        creator_id=current_user.id,
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

@router.get("/", response_model=List[schemas.ProblemRead])
def list_problems(difficulty: Optional[str] = Query(None), tag: Optional[str] = Query(None), db: Session = Depends(get_db)):
    query = db.query(db_models.Problem)
    if difficulty:
        query = query.filter(db_models.Problem.difficulty == difficulty)
    
    problems = query.all()
    
    if tag:
        problems = [p for p in problems if tag in p.tags]
            
    return problems

@router.put("/{id}", response_model=schemas.ProblemRead)
def update_problem(id: str, problem: schemas.ProblemCreate, db: Session = Depends(get_db), current_user: db_models.User = Depends(get_current_user)):
    db_problem = db.query(db_models.Problem).filter(db_models.Problem.id == id).first()
    if not db_problem:
        raise HTTPException(status_code=404, detail="Problem not found")    
    if db_problem.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="You are not the creator of this problem")
    
    db_problem.title = problem.title
    db_problem.difficulty = problem.difficulty
    db_problem.tags = problem.tags
    db_problem.description = problem.description
    db_problem.test_cases = [tc.model_dump(by_alias=True) for tc in problem.test_cases]
    
    db.commit()
    db.refresh(db_problem)
    return db_problem

@router.delete("/{id}")
def delete_problem(id: str, db: Session = Depends(get_db), current_user: db_models.User = Depends(get_current_user)):
    db_problem = db.query(db_models.Problem).filter(db_models.Problem.id == id).first()
    if not db_problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    if db_problem.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="You are not the creator of this problem")
    
    db.delete(db_problem)
    db.commit()
    return {"message": "Successfully deleted"}

@router.get("/leaderboard", response_model=List[schemas.LeaderboardRead])
def get_leaderboard(db: Session = Depends(get_db)):
    return db.query(db_models.User).order_by(db_models.User.total_score.desc()).limit(50).all()

@router.post("/{id}/submit", response_model=schemas.SubmissionResponse, tags=["Grading"])
async def submit_problem(
    id: str, 
    request: schemas.SubmissionRequest, 
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user)
):
    problem = db.query(db_models.Problem).filter(db_models.Problem.id == id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")

    already_solved = db.query(db_models.UserProblemScore).filter_by(
        user_id=current_user.id, challenge_id=id
    ).first() is not None

    passed_count = 0
    details = []
    test_cases = problem.test_cases 

    for i, tc in enumerate(test_cases):
        result = await compiler_instance.compile(request.code, request.language) 
        
        actual_output = result.get("stdout", "").strip()
        expected_output = tc.get("expected_output", "").strip()
        
        is_correct = result.get("success", False) and (actual_output == expected_output)
        
        if is_correct:
            passed_count += 1
            status = "Correct"
        else:
            status = "Wrong" if result.get("success") else "Error"

        details.append(schemas.TestCaseResult(
            case_number=i + 1,
            status=status,
            input=tc.get("input", ""),
            expected=expected_output,
            actual=actual_output if status == "Wrong" else result.get("stderr", "Error")
        ))

    final_status = "Accepted" if passed_count == len(test_cases) else "Rejected"
    
    if final_status == "Accepted" and not already_solved:
        points = 100
        current_user.total_score += points
        
        score_record = db_models.UserProblemScore(
            user_id=current_user.id,
            challenge_id=id,
            points_awarded=points
        )
        db.add(score_record)
        db.commit()
    
    return schemas.SubmissionResponse(
        status=final_status,
        total_cases=len(test_cases),
        passed_cases=passed_count,
        total_score=current_user.total_score,
        details=details
    )
