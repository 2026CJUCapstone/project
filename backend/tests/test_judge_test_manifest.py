"""Stored-case primitives: no claim that API/worker integration is enabled."""
from copy import deepcopy
import hashlib
import json
import zlib
import pytest
from sqlalchemy import event

from app.models import database as m
from app.models.judge_test_manifest import (
    MAX_SUITE_DATA_BYTES,MAX_TEST_DATA_BYTES,canonical_case,canonical_suite,references_in,
)
from app.services.judge_policy import content_hash,test_suite_hash as old_suite_hash
from app.services.judge_test_data import put_data
from app.services import judge_test_manifest as manifests
from tests.test_contests import env


def reference(data):
    return dict(digest='sha256:'+hashlib.sha256(data).hexdigest(),byteCount=len(data),encoding='utf-8')


def case(data=b'input\n',expected=b'answer\n'):
    return dict(kind='stored-v1',inputRef=reference(data),expectedOutputRef=reference(expected))


def save(db,env,data):
    put_data(db,data,reference(data)['digest'],env.admin.id)
    db.commit()


def test_legacy_inline_fingerprint_is_byte_for_byte_unchanged():
    sample=[dict(input='한글\r\n ',expected_output=' 1\n')]
    hidden=[dict(input='',expectedOutput='')]
    suite=canonical_suite(sample,hidden)
    assert content_hash(suite)==old_suite_hash(sample,hidden)
    assert suite['sample'][0]['input']=='한글\r\n '
    assert list(references_in(suite))==[]


def test_reference_aliases_are_canonical_and_input_is_not_mutated():
    original=case();snapshot=deepcopy(original)
    snake=dict(kind='stored-v1',input_ref={'digest':reference(b'input\n')['digest'],'byte_count':6},
        expected_output_ref={'digest':reference(b'answer\n')['digest'],'byte_count':7})
    assert canonical_case(snake,allow_reference=True)==original
    assert canonical_suite([], [original])['hidden'][0]==original
    assert original==snapshot
    for field in ('inputRef','expectedOutputRef'):
        changed=deepcopy(original);changed[field]['digest']='sha256:'+'a'*64
        assert content_hash(canonical_suite([], [changed]))!=content_hash(canonical_suite([], [original]))


@pytest.mark.parametrize('mutation',[
    'unknown-kind','missing-kind','inline-mixed','missing-ref','url','path','uppercase',
    'negative','oversize','float','boolean','string-size','encoding','extra','alias-conflict',
])
def test_ambiguous_or_unbounded_reference_is_rejected(mutation):
    raw=case()
    if mutation=='unknown-kind': raw['kind']='stored-v2'
    elif mutation=='missing-kind': raw.pop('kind')
    elif mutation=='inline-mixed': raw.update(input='secret',expected_output='hidden')
    elif mutation=='missing-ref': raw.pop('inputRef')
    elif mutation=='url': raw['inputRef']['digest']='https://example.test/private'
    elif mutation=='path': raw['inputRef']['digest']='../../private'
    elif mutation=='uppercase': raw['inputRef']['digest']='sha256:'+'A'*64
    elif mutation=='negative': raw['inputRef']['byteCount']=-1
    elif mutation=='oversize': raw['inputRef']['byteCount']=MAX_TEST_DATA_BYTES+1
    elif mutation=='float': raw['inputRef']['byteCount']=1.0
    elif mutation=='boolean': raw['inputRef']['byteCount']=True
    elif mutation=='string-size': raw['inputRef']['byteCount']='1'
    elif mutation=='encoding': raw['inputRef']['encoding']='base64'
    elif mutation=='extra': raw['inputRef']['url']='file:///etc/passwd'
    elif mutation=='alias-conflict': raw['input_ref']=deepcopy(raw['inputRef'])
    with pytest.raises(ValueError): canonical_case(raw,allow_reference=True)


def test_hidden_only_and_case_count_and_total_data_budget():
    raw=case()
    with pytest.raises(ValueError,match='samples'): canonical_suite([raw],[])
    for sample,hidden in (([],[]),([], [raw]*201),('not-a-list',[])):
        with pytest.raises(ValueError): canonical_suite(sample,hidden)
    raw['inputRef']['byteCount']=raw['expectedOutputRef']['byteCount']=MAX_TEST_DATA_BYTES
    count=MAX_SUITE_DATA_BYTES//(2*MAX_TEST_DATA_BYTES)
    assert len(canonical_suite([], [raw]*count)['hidden'])==count
    with pytest.raises(ValueError,match='budget'): canonical_suite([], [raw]*(count+1))
    conflict=case();conflict['expectedOutputRef']=dict(conflict['inputRef'],byteCount=1)
    with pytest.raises(ValueError,match='Conflicting'): canonical_suite([], [conflict])


def test_metadata_validation_never_selects_blob_and_materializes_only_requested_case(env,monkeypatch):
    first=case(b'first\n',b'answer 1\n');second=case(b'second\n',b'answer 2\n')
    with env.factory() as db:
        for data in (b'first\n',b'answer 1\n',b'second\n',b'answer 2\n'): save(db,env,data)
    with env.factory() as db:
        statements=[]
        def record(_conn,_cursor,statement,_params,_context,_many): statements.append(statement)
        engine=db.get_bind();event.listen(engine,'before_cursor_execute',record)
        try: suite=manifests.verify_reference_metadata(db,[],[first,second,first])
        finally: event.remove(engine,'before_cursor_execute',record)
        assert len(statements)==1 and 'compressed' not in statements[0].lower()
        loaded=[];original=manifests.load_data
        def load(session,digest):
            loaded.append(digest)
            return original(session,digest)
        monkeypatch.setattr(manifests,'load_data',load)
        assert manifests.materialize_case(db,suite['hidden'][0])==dict(input='first\n',expectedOutput='answer 1\n')
        assert loaded==[first['inputRef']['digest'],first['expectedOutputRef']['digest']]
        assert manifests.materialize_case(db,dict(input='inline',expected_output='ok'))==dict(input='inline',expectedOutput='ok')
        assert len(loaded)==2


def test_missing_misdeclared_and_corrupt_storage_never_become_empty_cases(env):
    raw=case()
    with env.factory() as db:
        with pytest.raises(ValueError,match='missing'): manifests.verify_reference_metadata(db,[],[raw])
        for data in (b'input\n',b'answer\n'): save(db,env,data)
        wrong=deepcopy(raw);wrong['inputRef']['byteCount']+=1
        with pytest.raises(ValueError): manifests.verify_reference_metadata(db,[],[wrong])
        with pytest.raises(ValueError): manifests.materialize_case(db,wrong)
        row=db.get(m.JudgeTestData,raw['inputRef']['digest']);row.compressed=zlib.compress(b'other\n');db.commit()
        # Metadata is intentionally cheap, not a full publication integrity scan.
        manifests.verify_reference_metadata(db,[],[raw])
        with pytest.raises(ValueError,match='digest'): manifests.materialize_case(db,raw)


def test_nine_megabyte_case_has_small_immutable_manifest_and_roundtrips(env):
    data=b'1000000\n'+b'-1000000 '*999999+b'-1000000\n'
    expected=b'-1000000 -1000000\n';raw=case(data,expected)
    with env.factory() as db:
        save(db,env,data);save(db,env,expected)
    with env.factory() as db:
        suite=manifests.verify_reference_metadata(db,[],[raw])
        assert len(json.dumps(suite).encode())<512
        hydrated=manifests.materialize_case(db,suite['hidden'][0])
        assert hydrated['input'].encode()==data and hydrated['expectedOutput'].encode()==expected
        assert db.query(m.ExecutionJob).count()==0  # Not yet a queued receipt.
