from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, update
from sqlalchemy.orm import Session
from app.api.routes.auth import get_current_user, get_optional_current_user
from app.core.database import get_db
from app.models import database as m
from app.services import learning as service
from app.services.contest_access import iso, now_utc


def private_cache(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(dependencies=[Depends(private_cache)])


class LearningUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bookmarked: bool
    note: str = Field(max_length=5000)
    reviewed: bool
    version: int = Field(ge=0)


def record_json(problem_id, record):
    return {"problemId": problem_id, "bookmarked": bool(record and record.bookmarked),
        "note": record.note if record else "", "reviewedAt": iso(record.reviewed_at) if record else None,
        "reviewed": bool(record and record.reviewed_at and (
            not record.last_attempt_at or record.reviewed_at >= record.last_attempt_at)),
        "version": record.version if record else 0}


def require_visible(db, problem_id):
    if not service.public_problems(db).filter(m.Problem.id == problem_id).first():
        raise HTTPException(404, "문제를 찾을 수 없습니다.")


@router.get("/tracks")
def tracks(db: Session = Depends(get_db), user=Depends(get_optional_current_user)):
    return {"tracks": [service.track_summary(db, t, user.id if user else None) for t in service.TRACKS],
        "signedIn": bool(user)}


@router.get("/tracks/{track_id}")
def track_detail(track_id: str, limit: int = Query(24, ge=1, le=100), offset: int = Query(0, ge=0, le=100000),
                 db: Session = Depends(get_db), user=Depends(get_optional_current_user)):
    track = next((t for t in service.TRACKS if t[0] == track_id), None)
    if track is None:
        raise HTTPException(404, "문제집을 찾을 수 없습니다.")
    query = service.for_track(service.public_problems(db), track)
    items = query.order_by(service.difficulty_order(), m.Problem.id).offset(offset).limit(limit).all()
    return {"track": service.track_summary(db, track, user.id if user else None),
        "items": service.learning_items(db, items, user.id if user else None),
        "total": query.count(), "offset": offset, "limit": limit}


@router.get("/recommendations")
def recommended(db: Session = Depends(get_db), user=Depends(get_optional_current_user)):
    return service.recommendations(db, user.id if user else None)


@router.get("/review")
def review(filter: Literal["unresolved", "bookmarked", "notes", "all"] = "unresolved",
           limit: int = Query(24, ge=1, le=100), offset: int = Query(0, ge=0, le=100000),
           db: Session = Depends(get_db), user=Depends(get_current_user)):
    record = m.ProblemLearningRecord
    query = service.public_problems(db).join(record, record.problem_id == m.Problem.id).filter(record.user_id == user.id)
    unresolved = (~service.solved_expression(user.id)) & record.last_verdict.in_(service.REVIEW_VERDICTS) & (
        or_(record.reviewed_at.is_(None), record.reviewed_at < record.last_attempt_at))
    if filter == "unresolved":
        query = query.filter(unresolved)
    elif filter == "bookmarked":
        query = query.filter(record.bookmarked.is_(True))
    elif filter == "notes":
        query = query.filter(record.note != "")
    else:
        query = query.filter(or_(unresolved, record.bookmarked.is_(True), record.note != ""))
    total = query.count()
    problems = query.order_by(record.last_attempt_at.desc(), m.Problem.id).offset(offset).limit(limit).all()
    return {"items": service.learning_items(db, problems, user.id), "total": total, "offset": offset, "limit": limit}


@router.get("/problems/{problem_id}")
def read_record(problem_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require_visible(db, problem_id)
    return record_json(problem_id, db.get(m.ProblemLearningRecord, (user.id, problem_id)))


@router.put("/problems/{problem_id}")
def write_record(problem_id: str, data: LearningUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require_visible(db, problem_id)
    record = m.ProblemLearningRecord
    # Concurrent first writes and updates both obey the same optimistic version fence.
    db.execute(service.insert_for(db)(record).values(user_id=user.id, problem_id=problem_id,
        bookmarked=False, note="", version=0).on_conflict_do_nothing(index_elements=["user_id", "problem_id"]))
    result = db.execute(update(record).where(record.user_id == user.id, record.problem_id == problem_id,
        record.version == data.version).values(bookmarked=data.bookmarked, note=data.note,
            reviewed_at=now_utc() if data.reviewed else None, version=record.version + 1))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "다른 창에서 변경되었습니다. 최신 기록을 확인한 뒤 다시 저장하세요.")
    db.commit()
    db.expire_all()
    return record_json(problem_id, db.get(record, (user.id, problem_id)))
