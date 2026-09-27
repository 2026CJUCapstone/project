"""One transaction creates only a private contest plus private sources.

Package IDs are globally unique. Retries return the original server mapping;
they never overwrite later administrative edits or invent a new package ID.
"""
import copy
from fastapi import HTTPException
from app.models import database as m
from app.services.runtime_registry import execution_lock
from app.services.judge_policy import content_hash


def package_read(db,package_id,user,*,replayed=True):
    receipt=db.get(m.ContestPackageImport,package_id)
    if receipt is None or receipt.actor_id!=user.id: raise HTTPException(404,'등록 기록을 찾을 수 없습니다.')
    contest=db.get(m.Contest,receipt.contest_id)
    if contest is None: raise HTTPException(409,'원래 대회가 없습니다. 자동으로 다시 만들지 않습니다.')
    # Editing even just the schedule recreates contest-problem row IDs. Keep the
    # immutable receipt, but resolve current links rather than returning dead IDs.
    rows=db.query(m.ContestProblem).filter_by(contest_id=contest.id).all()
    current={row.problem_id:row.id for row in rows}
    original=copy.deepcopy(receipt.problem_ids)
    mapping=[{**entry,'contestProblemId':current.get(entry['problemId']),
              'removed':entry['problemId'] not in current} for entry in original]
    return dict(packageId=receipt.package_id,revision=receipt.revision,manifestHash=receipt.manifest_hash,
        contestId=receipt.contest_id,problems=mapping,originalProblems=original,
        replayed=replayed,currentPublished=bool(contest.published))


def import_package(db,data,user):
    from app.api.routes.contests import save_contest
    from app.services.contests import problem_rows
    if user.role!='admin': raise HTTPException(403,'관리자 권한이 필요합니다.')
    execution_lock(db)
    stamp=content_hash(data.model_dump(mode='json',by_alias=True))
    old=db.get(m.ContestPackageImport,data.package_id)
    if old:
        if old.actor_id!=user.id or old.manifest_hash!=stamp:
            raise HTTPException(409,'이미 등록된 패키지 ID입니다. 기존 대회를 확인하세요.')
        return package_read(db,data.package_id,user)
    try:
        result=save_contest(db,None,data.contest_write(),user,commit=False)
        rows=problem_rows(db,result['id'])
        mapping=[]
        for entry,row in zip(data.entries,rows,strict=True):
            metadata=entry.metadata.model_dump(mode='json',by_alias=True)
            db.add(m.ProblemAuthoring(problem_id=row.problem_id,metadata_json=metadata))
            row.snapshot={**copy.deepcopy(row.snapshot),'authoring':metadata}
            mapping.append(dict(key=entry.key,problemId=row.problem_id,contestProblemId=row.id))
        db.add(m.ContestPackageImport(package_id=data.package_id,revision=data.revision,actor_id=user.id,
            manifest_hash=stamp,contest_id=result['id'],problem_ids=mapping))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return package_read(db,data.package_id,user,replayed=False)
