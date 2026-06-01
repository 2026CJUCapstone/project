from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models import database as db_models
from app.models import schemas

router = APIRouter()


def _validate_scope(scope: str) -> str:
    normalized_scope = scope.strip() or "main"
    if len(normalized_scope) > settings.CODE_PROJECT_SCOPE_MAX_LENGTH:
        raise HTTPException(status_code=400, detail="저장 범위가 너무 깁니다.")
    if "/" in normalized_scope or "\\" in normalized_scope or "\x00" in normalized_scope:
        raise HTTPException(status_code=400, detail="저장 범위 형식이 올바르지 않습니다.")
    return normalized_scope


def _validate_code_size(code: str) -> None:
    if len(code.encode("utf-8")) > settings.CODE_PROJECT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="저장할 코드가 너무 큽니다.")


def _serialize_project(project: db_models.CodeProject) -> schemas.CodeProjectRead:
    return schemas.CodeProjectRead(
        id=project.id,
        scope=project.scope,
        title=project.title,
        language=project.language,
        code=project.code,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("/", response_model=List[schemas.CodeProjectRead])
def list_projects(
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user),
):
    projects = (
        db.query(db_models.CodeProject)
        .filter(db_models.CodeProject.user_id == current_user.id)
        .order_by(db_models.CodeProject.updated_at.desc())
        .all()
    )
    return [_serialize_project(project) for project in projects]


@router.get("/{scope:path}", response_model=schemas.CodeProjectRead)
def get_project(
    scope: str,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user),
):
    normalized_scope = _validate_scope(scope)
    project = (
        db.query(db_models.CodeProject)
        .filter(db_models.CodeProject.user_id == current_user.id, db_models.CodeProject.scope == normalized_scope)
        .first()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _serialize_project(project)


@router.put("/{scope:path}", response_model=schemas.CodeProjectRead)
def upsert_project(
    scope: str,
    payload: schemas.CodeProjectUpsert,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user),
):
    normalized_scope = _validate_scope(scope)
    _validate_code_size(payload.code)
    project = (
        db.query(db_models.CodeProject)
        .filter(
            db_models.CodeProject.user_id == current_user.id,
            db_models.CodeProject.scope == normalized_scope,
        )
        .first()
    )

    if project is None:
        project_count = (
            db.query(db_models.CodeProject)
            .filter(db_models.CodeProject.user_id == current_user.id)
            .count()
        )
        if project_count >= settings.CODE_PROJECT_MAX_PER_USER:
            raise HTTPException(status_code=409, detail="저장 가능한 프로젝트 수를 초과했습니다.")
        project = db_models.CodeProject(
            user_id=current_user.id,
            scope=normalized_scope,
            title=payload.title.strip() or normalized_scope,
            language=payload.language,
            code=payload.code,
        )
        db.add(project)
    else:
        project.title = payload.title.strip() or project.title
        project.language = payload.language
        project.code = payload.code
        db.add(project)

    db.commit()
    db.refresh(project)
    return _serialize_project(project)


@router.delete("/{scope:path}", status_code=204)
def delete_project(
    scope: str,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(get_current_user),
):
    normalized_scope = _validate_scope(scope)
    deleted = (
        db.query(db_models.CodeProject)
        .filter(db_models.CodeProject.user_id == current_user.id, db_models.CodeProject.scope == normalized_scope)
        .delete(synchronize_session=False)
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    db.commit()
