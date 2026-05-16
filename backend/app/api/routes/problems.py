from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.models import database as db_models
from app.models import schemas
from app.api.routes.auth import get_current_user, get_optional_current_user
from app.services.compiler import compiler_instance

router = APIRouter()


def _normalize_problem_test_cases(raw_test_cases: object) -> tuple[list[dict], list[dict]]:
    def normalize_case(raw_case: object) -> dict:
        if not isinstance(raw_case, dict):
            return {"input": "", "expected_output": ""}
        return {
            "input": raw_case.get("input", ""),
            "expected_output": raw_case.get("expected_output", raw_case.get("expectedOutput", "")),
        }

    if isinstance(raw_test_cases, dict):
        sample_cases = raw_test_cases.get("sample") or raw_test_cases.get("test_cases") or []
        hidden_cases = raw_test_cases.get("hidden") or []
    elif isinstance(raw_test_cases, list):
        sample_cases = raw_test_cases
        hidden_cases = []
    else:
        sample_cases = []
        hidden_cases = []

    return [normalize_case(test_case) for test_case in sample_cases], [normalize_case(test_case) for test_case in hidden_cases]


def _serialize_problem(problem: db_models.Problem) -> dict:
    sample_cases, hidden_cases = _normalize_problem_test_cases(problem.test_cases)
    return {
        "id": problem.id,
        "creator_id": problem.creator_id,
        "title": problem.title,
        "difficulty": problem.difficulty,
        "tags": problem.tags,
        "description": problem.description,
        "test_cases": sample_cases,
        "hidden_test_cases": hidden_cases,
        "created_at": problem.created_at,
    }


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
        test_cases={
            "sample": [tc.model_dump() for tc in problem.test_cases],
            "hidden": [tc.model_dump() for tc in problem.hidden_test_cases],
        }
    )
    db.add(db_problem)
    db.commit()
    db.refresh(db_problem)
    return _serialize_problem(db_problem)

@router.get("/", response_model=List[schemas.ProblemRead])
def list_problems(difficulty: Optional[str] = Query(None), tag: Optional[str] = Query(None), db: Session = Depends(get_db)):
    query = db.query(db_models.Problem)
    if difficulty:
        query = query.filter(db_models.Problem.difficulty == difficulty)
    
    problems = query.all()
    
    if tag:
        problems = [p for p in problems if tag in p.tags]
            
    return [_serialize_problem(problem) for problem in problems]

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
    db_problem.test_cases = {
        "sample": [tc.model_dump() for tc in problem.test_cases],
        "hidden": [tc.model_dump() for tc in problem.hidden_test_cases],
    }
    
    db.commit()
    db.refresh(db_problem)
    return _serialize_problem(db_problem)

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
            hashed_password="",
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

@router.post("/{id}/submit", response_model=schemas.SubmissionResponse, tags=["Grading"])
async def submit_problem(
    id: str, 
    request: schemas.SubmissionRequest, 
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user)
):
    problem = db.query(db_models.Problem).filter(db_models.Problem.id == id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")

    already_solved = False
    if current_user is not None:
        already_solved = db.query(db_models.UserProblemScore).filter_by(
            user_id=current_user.id, challenge_id=id
        ).first() is not None

    sample_cases, hidden_cases = _normalize_problem_test_cases(problem.test_cases)
    details: list[schemas.TestCaseResult] = []
    sample_passed_count = 0
    hidden_passed_count = 0

    async def run_case(tc: dict, case_number: int, phase: str, visible: bool) -> schemas.TestCaseResult:
        result = await compiler_instance.run(
            source_code=request.code,
            language=request.language,
            stdin=tc.get("input", ""),
        )

        actual_output = result.get("stdout", "").strip()
        expected_output = tc.get("expected_output", "").strip()
        is_correct = result.get("exit_code", 1) == 0 and actual_output == expected_output
        status = "Correct" if is_correct else ("Wrong" if result.get("exit_code", 1) == 0 else "Error")
        return schemas.TestCaseResult(
            case_number=case_number,
            phase=phase,
            is_visible=visible,
            status=status,
            input=tc.get("input", "") if visible else "",
            expected=expected_output if visible else "",
            actual=(actual_output if status != "Error" else result.get("stderr", "Error")) if visible else "",
        )

    for index, tc in enumerate(sample_cases, start=1):
        case_result = await run_case(tc, index, "sample", True)
        details.append(case_result)
        if case_result.status == "Correct":
            sample_passed_count += 1

    hidden_completed = sample_passed_count == len(sample_cases)

    if hidden_completed:
        for index, tc in enumerate(hidden_cases, start=1):
            case_result = await run_case(tc, index, "hidden", False)
            details.append(case_result)
            if case_result.status == "Correct":
                hidden_passed_count += 1

    total_cases = len(sample_cases) + len(hidden_cases)
    passed_cases = sample_passed_count + hidden_passed_count

    if sample_passed_count != len(sample_cases):
        final_status = "SampleFailed"
    elif hidden_completed and hidden_passed_count == len(hidden_cases):
        final_status = "Accepted"
    else:
        final_status = "Rejected"

    total_score = current_user.total_score if current_user is not None else 0
    if final_status == "Accepted" and current_user is not None and not already_solved:
        points = 100
        current_user.total_score += points
        total_score = current_user.total_score

        score_record = db_models.UserProblemScore(
            user_id=current_user.id,
            challenge_id=id,
            points_awarded=points
        )
        db.add(score_record)
        db.commit()

    return schemas.SubmissionResponse(
        status=final_status,
        total_cases=total_cases,
        passed_cases=passed_cases,
        sample_total_cases=len(sample_cases),
        sample_passed_cases=sample_passed_count,
        hidden_total_cases=len(hidden_cases),
        hidden_passed_cases=hidden_passed_count,
        hidden_completed=hidden_completed,
        total_score=total_score,
        details=details,
    )
