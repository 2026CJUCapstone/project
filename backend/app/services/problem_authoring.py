"""Private provenance and append-only, exact-content review evidence."""
import copy
from fastapi import HTTPException
from sqlalchemy import func
from app.models import database as m
from app.models.problem_authoring import AuthoringMetadata
from app.services.judge_policy import content_hash, freeze_stored_submission, validate_stored_publication
from app.services.contest_access import iso, now_utc, utc_naive
from app.services.runtime_registry import execution_lock
from app.core.config import settings

CATEGORIES=('sources','statement','tests','resources')


def attach_metadata(db,problem_id,snapshot):
    record=db.get(m.ProblemAuthoring,problem_id)
    if record is not None: snapshot['authoring']=copy.deepcopy(record.metadata_json)
    return snapshot


def fingerprint(snapshot):
    # Do not include schedule, contest points, or mutable IDs in content review.
    keys=('title','description','difficulty','tags','practicePoints','sample','hidden','judgePolicy','authoring')
    return content_hash({key:snapshot.get(key) for key in keys})


def require_problem(db,problem_id,*,editable=False):
    problem=db.get(m.Problem,problem_id)
    if problem is None or problem.deleted_at is not None: raise HTTPException(404,'문제를 찾을 수 없습니다.')
    if editable:
        for contest in db.query(m.Contest).join(m.ContestProblem).filter(m.ContestProblem.problem_id==problem_id).all():
            if contest.published and utc_naive(contest.starts_at)<=now_utc():
                raise HTTPException(409,'시작한 대회의 검수·출처 기록은 변경할 수 없습니다.')
    return problem


def current_snapshot(db,problem):
    from app.api.routes.contests import snapshot
    return attach_metadata(db,problem.id,snapshot(problem))


def decisions(db,problem_id,stamp):
    rows=db.query(m.ProblemReviewEvent).filter_by(problem_id=problem_id,fingerprint=stamp).order_by(m.ProblemReviewEvent.sequence).all()
    return {r.category:r for r in rows}


def _review_projection(db,problem_id,snap):
    stamp=fingerprint(snap)
    latest=decisions(db,problem_id,stamp)
    events=db.query(m.ProblemReviewEvent).filter_by(problem_id=problem_id).order_by(m.ProblemReviewEvent.sequence.desc()).limit(100).all()
    return dict(problemId=problem_id,fingerprint=stamp,metadata=snap.get('authoring'),
        categories={key:latest[key].decision if key in latest else 'pending' for key in CATEGORIES},
        events=[dict(id=e.id,actorId=e.actor_id,fingerprint=e.fingerprint,category=e.category,decision=e.decision,
            note=e.note,sequence=e.sequence,createdAt=iso(e.created_at)) for e in events])


def review_read(db,problem_id):
    problem=require_problem(db,problem_id)
    return _review_projection(db,problem_id,current_snapshot(db,problem))


def review_read_snapshot(db,problem_id,snapshot):
    """Project review evidence against one saved contest snapshot, not mutable source state."""
    require_problem(db,problem_id)
    return _review_projection(db,problem_id,copy.deepcopy(snapshot))


def assert_reviewed(db,problem_id,snapshot,*,contest_id=None,contest_problem_id=None,require_tracked=False):
    if db.get(m.ProblemAuthoring,problem_id) is None:
        if require_tracked:
            raise HTTPException(409,'신규 비공개 문제에는 출처·검수 기록과 기준 풀이 검증이 필요합니다.')
        return  # Existing public content stays compatible.
    if not snapshot.get('authoring'): raise HTTPException(409,'출처와 검수 스냅샷이 필요합니다.')
    stamp=fingerprint(snapshot)
    latest=decisions(db,problem_id,stamp)
    missing=[k for k in CATEGORIES if k not in latest or latest[k].decision!='approved']
    if missing: raise HTTPException(409,'현재 문제 버전의 검수가 필요합니다: '+', '.join(missing))
    assert_reference_validated(
        db,
        problem_id,
        snapshot,
        contest_id=contest_id,
        contest_problem_id=contest_problem_id,
    )


def assert_reference_validated(db,problem_id,snapshot,*,contest_id,contest_problem_id=None):
    """Require accepted reference runs for the exact immutable snapshot."""
    stamp=fingerprint(snapshot)
    try:
        metadata=AuthoringMetadata.model_validate(snapshot['authoring'])
    except ValueError:
        raise HTTPException(409,'출처 기록 형식이 올바르지 않습니다.') from None
    snapshot_hash=content_hash(snapshot)
    missing_validations=[]
    for language in metadata.required_languages:
        references=[asset for asset in metadata.assets
                    if asset.role=='reference' and asset.language==language]
        if len(references)!=1:
            raise HTTPException(409,f'{language} 기준 풀이 파일 지문은 정확히 하나여야 합니다.')
        try:
            contract=freeze_stored_submission(snapshot.get('judgePolicy'),language,
                snapshot.get('sample',[]),snapshot.get('hidden',[]),settings=settings)
        except ValueError as exc:
            raise HTTPException(409,str(exc)) from None
        query=db.query(m.ProblemValidationAttestation.job_id).filter_by(
            problem_id=problem_id,
            problem_snapshot_hash=snapshot_hash,
            authoring_fingerprint=stamp,
            language=language,
            source_hash=references[0].digest,
            reference_asset_digest=references[0].digest,
            policy_hash=contract.get('policyHash'),
            test_suite_hash=contract.get('testSuiteHash'),
        )
        if contest_id is not None:
            query=query.filter_by(contest_id=contest_id)
        if contest_problem_id is not None:
            query=query.filter_by(contest_problem_id=contest_problem_id)
        if query.first() is None:
            missing_validations.append(language)
    if missing_validations:
        raise HTTPException(409,'현재 기준 풀이의 전체 테스트 통과 검증이 필요합니다: '+', '.join(missing_validations))


def update_metadata(db,problem_id,data,user):
    execution_lock(db)
    problem=require_problem(db,problem_id,editable=True)
    snap=current_snapshot(db,problem)
    if fingerprint(snap)!=data.expected_fingerprint: raise HTTPException(409,'문제가 변경되었습니다. 최신 내용을 다시 확인하세요.')
    record=db.get(m.ProblemAuthoring,problem_id)
    if record is None:
        record=m.ProblemAuthoring(problem_id=problem_id);db.add(record)
    record.metadata_json=data.metadata.model_dump(mode='json',by_alias=True)
    record.updated_at=now_utc()
    # Metadata participates in the reviewed fingerprint. Saving new provenance
    # invalidates any prior publication approval until the exact new version is
    # reviewed and its reference implementations pass again.
    problem.publication_review_required=True
    problem.publication_approved_at=None
    db.commit()
    from app.services.rating import invalidate_rating_cache
    invalidate_rating_cache()
    return review_read(db,problem_id)


def append_review(db,problem_id,data,user):
    execution_lock(db)
    request_hash=content_hash({'problemId':problem_id,**data.model_dump(mode='json',by_alias=True)})
    old=db.query(m.ProblemReviewEvent).filter_by(actor_id=user.id,request_id=data.request_id).first()
    if old:
        if old.request_hash!=request_hash: raise HTTPException(409,'동일 요청 ID를 다른 검수에 사용할 수 없습니다.')
        return review_read(db,problem_id)
    problem=require_problem(db,problem_id,editable=True)
    snap=current_snapshot(db,problem);stamp=fingerprint(snap)
    if stamp!=data.expected_fingerprint: raise HTTPException(409,'문제가 변경되었습니다. 최신 내용을 다시 확인하세요.')
    validate_review(db,snap,data.category,data.decision)
    sequence=(db.query(func.max(m.ProblemReviewEvent.sequence)).filter_by(problem_id=problem_id).scalar() or 0)+1
    db.add(m.ProblemReviewEvent(problem_id=problem_id,actor_id=user.id,request_id=data.request_id,request_hash=request_hash,
        fingerprint=stamp,category=data.category,decision=data.decision,note=data.note,sequence=sequence))
    publication_changed = (
        data.decision=='rejected'
        and problem.publication_review_required is True
        and problem.publication_approved_at is not None
    )
    if data.decision=='rejected' and problem.publication_review_required is True:
        problem.publication_approved_at=None
    db.commit()
    if publication_changed:
        from app.services.rating import invalidate_rating_cache
        invalidate_rating_cache()
    return review_read(db,problem_id)


def validate_review(db,snap,category,decision):
    """Shared evidence checks; caller supplies the exact immutable review target."""
    if not snap.get('authoring'): raise HTTPException(409,'출처 기록을 먼저 작성하세요.')
    try:
        meta=AuthoringMetadata.model_validate(snap['authoring'])
    except ValueError:
        raise HTTPException(409,'출처 기록 형식이 올바르지 않습니다.') from None
    if decision=='approved':
        if category=='sources' and any(s.reuse_basis=='pending' or not s.reuse_evidence.strip() for s in meta.sources):
            raise HTTPException(409,'이용 조건의 확인 근거가 없는 출처를 승인할 수 없습니다.')
        if category=='tests':
            roles={a.role for a in meta.assets}
            languages={a.language for a in meta.assets if a.role=='reference'}
            if not {'validator','generator','wrong_solution'}<=roles or not set(meta.required_languages)<=languages:
                raise HTTPException(409,'기준 풀이·검증기·생성기·오답의 파일 지문이 필요합니다.')
        if category=='resources':
            try:
                from app.services.judge_test_manifest import validate_stored_cases
                validate_stored_cases(db,snap['sample'],snap['hidden'],integrity=True)
                validate_stored_publication(snap['judgePolicy'],snap['sample'],snap['hidden'],settings=settings)
                if not set(meta.required_languages)<=set((snap['judgePolicy'] or {}).get('profiles',{})):
                    raise ValueError('필수 언어의 측정 정책이 누락되었습니다.')
            except ValueError as exc: raise HTTPException(409,str(exc)) from None
