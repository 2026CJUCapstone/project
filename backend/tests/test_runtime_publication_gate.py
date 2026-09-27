"""Operator approval is separate from uploaded evidence, and is not liveness."""
from copy import deepcopy
import hashlib
import json

import pytest
from httpx import AsyncClient,ASGITransport

from app.core.config import settings
from app.main import app
from app.models import database as m
from app.models.judge_policy import JudgePolicy
from app.services import judge_runtime_registry as runtime_registry
from app.services.judge_policy import (
    validate_stored_publication,freeze_stored_submission,resource_fingerprint)
from tests.test_judge_policy import policy_fixture,install_synthetic_registry,SAMPLE,HIDDEN
from tests.test_judge_policy_persistence import problem_body
from tests.test_contests import env,headers


@pytest.mark.parametrize('change',['missing','empty','malformed','image','launcher','toolchain','version','class','language'])
def test_registry_mismatch_blocks_publication_and_receipt(tmp_path,monkeypatch,change):
    path=install_synthetic_registry(tmp_path,monkeypatch)
    raw=json.loads(path.read_text());entry=next(e for e in raw['runtimes'] if e['language']=='python')
    if change=='missing': monkeypatch.setattr(settings,'JUDGE_RUNTIME_REGISTRY',str(tmp_path/'missing.json'))
    elif change=='empty': monkeypatch.setattr(settings,'JUDGE_RUNTIME_REGISTRY','')
    elif change=='malformed': path.write_text('{invalid')
    else:
        key={'image':'imageDigest','launcher':'launcherDigest','toolchain':'toolchainProfile','version':'runtimeVersion',
             'class':'workerClass','language':'language'}[change]
        entry[key]='sha256:'+'9'*64 if change in ('image','launcher') else 'different'
        path.write_text(json.dumps(raw))
    for validate in (lambda:validate_stored_publication(policy_fixture(),SAMPLE,HIDDEN,settings=settings),
                     lambda:freeze_stored_submission(policy_fixture(),'python',SAMPLE,HIDDEN,settings=settings)):
        with pytest.raises(ValueError,match='등록부'): validate()
    # Nothing retroactively turns old unmeasured submissions into measured jobs.
    assert freeze_stored_submission(None,'python',SAMPLE,HIDDEN,settings=settings)['kind']=='legacy-v1'


def test_archived_launcher_marked_admit_new_still_blocks_publication(tmp_path,monkeypatch):
    old=b"print('archived supervisor')\n"
    current=b"print('current supervisor')\n"
    old_digest='sha256:'+hashlib.sha256(old).hexdigest()
    active=tmp_path/'active.py';active.write_bytes(current)
    archive=tmp_path/'archive';archive.mkdir()
    (archive/('sha256-'+old_digest[7:]+'.py')).write_bytes(old)
    monkeypatch.setattr(runtime_registry,'LAUNCHER_PATH',active)
    monkeypatch.setattr(runtime_registry,'LAUNCHER_ARCHIVE_DIR',archive)

    policy=policy_fixture()
    policy['profiles']['python']['launcherDigest']=old_digest
    parsed=JudgePolicy.model_validate(policy)
    policy['evidence']['python']['resourceFingerprint']=resource_fingerprint(parsed,'python')
    profile=policy['profiles']['python']
    registration={'language':'python',**{key:profile[key] for key in (
        'runtimeId','runtimeVersion','imageDigest','workerClass',
        'toolchainProfile','launcherDigest')},'admitNew':True}
    path=tmp_path/'runtime-registry.json'
    path.write_text(json.dumps({'version':2,'runtimes':[registration]}),encoding='utf-8')
    monkeypatch.setattr(settings,'JUDGE_RUNTIME_REGISTRY',str(path))

    with pytest.raises(ValueError,match='등록부'):
        validate_stored_publication(policy,SAMPLE,HIDDEN,settings=settings)


@pytest.mark.asyncio
async def test_missing_registry_rolls_back_public_creation_and_retry_keeps_original_receipt(env,monkeypatch):
    path=settings.JUDGE_RUNTIME_REGISTRY
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        monkeypatch.setattr(settings,'JUDGE_RUNTIME_REGISTRY','')
        response=await client.post('/api/v1/problems/',json=problem_body(),headers=headers(env.admin))
        assert response.status_code==409 and '등록부' in response.text
        with env.factory() as db: assert db.query(m.Problem).count()==0
        monkeypatch.setattr(settings,'JUDGE_RUNTIME_REGISTRY',path)
        response=await client.post('/api/v1/problems/',json=problem_body(),headers=headers(env.admin))
        assert response.status_code==200,response.text
        pid=response.json()['id'];url='/api/v1/problems/'+pid+'/submit'
        with env.factory() as db:
            db.get(m.Problem,pid).publication_approved_at=env.clock[0]
            db.commit()
        auth={**headers(env.alice),'X-Request-ID':'eeeeeeee-aaaa-4444-9999-123456789abc'}
        body=dict(code='print(42)',language='python')
        first=await client.post(url,json=body,headers=auth)
        assert first.status_code in (200,202),first.text
        with env.factory() as db: original=deepcopy(db.get(m.ExecutionJob,first.json()['executionId']).payload)
        monkeypatch.setattr(settings,'JUDGE_RUNTIME_REGISTRY','')
        retry=await client.post(url,json=body,headers=auth)
        assert retry.status_code==first.status_code and retry.json()['executionId']==first.json()['executionId']
        assert (await client.post(url,json=body,headers={**auth,'X-Request-ID':'ffffffff-aaaa-4444-9999-123456789abc'})).status_code==409
        with env.factory() as db: assert db.get(m.ExecutionJob,first.json()['executionId']).payload==original
