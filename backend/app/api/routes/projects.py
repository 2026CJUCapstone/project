from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.core.database import get_db
from app.models import database as db_models
from app.models import schemas

router = APIRouter()


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
    project = (
        db.query(db_models.CodeProject)
        .filter(db_models.CodeProject.user_id == current_user.id, db_models.CodeProject.scope == scope)
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
    normalized_scope = scope.strip() or "main"
    project = (
        db.query(db_models.CodeProject)
        .filter(
            db_models.CodeProject.user_id == current_user.id,
            db_models.CodeProject.scope == normalized_scope,
        )
        .first()
    )

    if project is None:
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
    deleted = (
        db.query(db_models.CodeProject)
        .filter(db_models.CodeProject.user_id == current_user.id, db_models.CodeProject.scope == scope)
        .delete(synchronize_session=False)
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    db.commit()
