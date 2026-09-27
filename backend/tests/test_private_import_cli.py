"""Offline importer transport tests; no network or operating database."""
import io
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4
from urllib.error import HTTPError, URLError

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts import import_private_contest as cli
from app.models.problem_authoring import PrivateContestPackage
from app.models.problem_authoring import MAX_PACKAGE_BYTES
from app.models.judge_test_manifest import MAX_TEST_DATA_BYTES, canonical_suite
from app.services.judge_policy import content_hash
from tools.freshman_contest.stress_cases import iter_cases


@pytest.fixture
def manifest():
    return PrivateContestPackage.model_validate(dict(schemaVersion=1,packageId='offline-fixture',revision=1,
        title='Synthetic fixture',startsAt='2030-01-01T01:00:00Z',endsAt='2030-01-01T02:00:00Z',
        entries=[dict(key='A',points=1,problem=dict(title='Fixture',description='Synthetic only',
            difficulty='iron5',tags=[],points=1,testCases=[dict(input='private-input',expectedOutput='private-output')]),
            metadata=dict(sources=[dict(url='https://example.com',title='Synthetic source')],
                adaptationNotes='No actual permission implied',requiredLanguages=['python']))]))


class Reply(io.BytesIO):
    status=200
    headers={'Cache-Control':'no-store','Content-Encoding':'identity'}


class Transport:
    def __init__(self,reply): self.reply=reply;self.calls=[]
    def open(self,request,timeout):
        self.calls.append((request,timeout))
        if isinstance(self.reply,Exception): raise self.reply
        return Reply(json.dumps(self.reply).encode())


def receipt(manifest):
    row=dict(key='A',problemId=str(uuid4()),contestProblemId=str(uuid4()))
    return dict(packageId=manifest.package_id,revision=1,manifestHash=cli.digest(manifest),contestId=str(uuid4()),
        replayed=False,currentPublished=False,problems=[{**row,'removed':False}],originalProblems=[row])


def test_canonical_digest_matches_server_and_dry_run_never_reads_token_or_network(manifest,tmp_path,monkeypatch,capsys):
    path=tmp_path/'manifest.json';path.write_bytes(cli.canonical(manifest))
    assert cli.digest(manifest)==content_hash(manifest.model_dump(mode='json',by_alias=True))
    def forbidden(*_args,**_kwargs): raise AssertionError('No transport/credential access on validation')
    monkeypatch.setattr(cli,'build_opener',forbidden)
    original_get=cli.os.environ.get
    def guarded_env(key,*args):
        if key=='CONTEST_IMPORT_TOKEN': return forbidden()
        return original_get(key,*args)
    monkeypatch.setattr(cli.os.environ,'get',guarded_env)
    assert cli.main([str(path)])==0
    output=capsys.readouterr().out
    assert json.loads(output)['mode']=='validation-only'
    assert 'private-input' not in output and 'private-output' not in output


def test_package_payload_fits_the_normal_proxy_limit(manifest,tmp_path):
    body=manifest.model_dump(mode='json',by_alias=True)
    body['entries'][0]['problem']['testCases'][0]['input']='x'*MAX_PACKAGE_BYTES
    with pytest.raises(ValueError,match='aggregate byte budget'):
        PrivateContestPackage.model_validate(body)
    path=tmp_path/'oversized.json'
    path.write_text(json.dumps(body),encoding='utf-8')
    with pytest.raises(ValueError,match='request-size limit'):
        cli.read_manifest(path)


@pytest.mark.parametrize('letter,name',[
    ('C','c-maximum-extrema-negative-repetitions'),
    ('E','e-maximum-case-insensitive-tie'),
    ('E','e-maximum-case-insensitive-winner'),
    ('I','i-maximum-single-source-frontier'),
])
def test_freshman_maximum_input_uses_stored_reference_without_changing_limits(manifest,letter,name):
    case=next(item for item in iter_cases(letter) if item.name==name)
    raw=case.input_text.encode('utf-8')
    answer=case.expected_output.encode('utf-8')
    assert MAX_PACKAGE_BYTES < len(raw) <= MAX_TEST_DATA_BYTES
    body=manifest.model_dump(mode='json',by_alias=True)
    problem=body['entries'][0]['problem']
    problem['hiddenTestCases']=[{'input':case.input_text,'expectedOutput':case.expected_output}]
    with pytest.raises(ValueError,match='byte budget'):
        PrivateContestPackage.model_validate(body)
    def reference(data):
        return {'digest':'sha256:'+hashlib.sha256(data).hexdigest(),'byteCount':len(data),'encoding':'utf-8'}
    stored={'kind':'stored-v1','inputRef':reference(raw),'expectedOutputRef':reference(answer)}
    problem['hiddenTestCases']=[stored]
    package=PrivateContestPackage.model_validate(body)
    assert len(cli.canonical(package))<=MAX_PACKAGE_BYTES
    assert canonical_suite([], [stored])['hidden']==[stored]


@pytest.mark.parametrize('base',['http://example.com/api/v1','https://user:pw@example.com/api/v1',
    'https://example.com/api/v1?x=1','https://example.com/api/v1#frag','https://example.com/api/v2',
    'file:///api/v1','https://example.com:99999/api/v1','https://example.com\\evil/api/v1',
    'https://example.com/\napi/v1'])
def test_unsafe_target_rejected_before_transport(manifest,base):
    sender=Transport(receipt(manifest))
    with pytest.raises(ValueError): cli.apply_manifest(manifest,base,'test-token',opener=sender)
    assert sender.calls==[]


@pytest.mark.parametrize('base',['http://127.0.0.1:8888/api/v1','http://[::1]:8888/api/v1',
                               'https://example.com/webcompiler/api/v1/'])
def test_explicit_transport_sends_same_canonical_manifest_only_once(manifest,base):
    response=receipt(manifest)
    sender=Transport(response)
    result=cli.apply_manifest(manifest,base,'test-token',opener=sender)
    assert len(sender.calls)==1
    request,timeout=sender.calls[0]
    assert request.method=='POST' and request.data==cli.canonical(manifest) and timeout==30
    assert request.full_url.endswith('/contests/packages/import')
    assert request.get_header('Authorization')=='Bearer test-token'
    assert request.get_header('Accept-encoding')=='identity'
    assert request.get_header('Cache-control')=='no-store'


@pytest.mark.parametrize('error',[URLError('synthetic'),HTTPError('https://example.com',302,'redirect',{},None),
                                HTTPError('https://example.com',409,'conflict',{},None)])
def test_uncertain_or_conflicting_response_never_retried(manifest,error):
    sender=Transport(error)
    with pytest.raises(ValueError): cli.apply_manifest(manifest,'https://example.com/api/v1','test-token',opener=sender)
    assert len(sender.calls)==1


def test_redirect_handler_never_forwards_credentials():
    assert cli.NoRedirect().redirect_request(None,None,307,'redirect',{},'https://elsewhere') is None


@pytest.mark.parametrize('mutation',['hash','mapping','id','removed','extra'])
def test_wrong_receipt_is_not_success(manifest,mutation):
    response=receipt(manifest)
    if mutation=='hash': response['manifestHash']='sha256:'+'0'*64
    elif mutation=='mapping': response['problems'][0]['key']='B'
    elif mutation=='id': response['contestId']='arbitrary terminal text'
    elif mutation=='removed': response['problems'][0]['removed']=True
    else: response['problems'][0]['untrustedExtra']='secret-server-content'
    with pytest.raises(ValueError,match='Receipt mismatch'):
        cli.apply_manifest(manifest,'https://example.com/api/v1','test-token',opener=Transport(response))


def test_invalid_manifest_does_not_echo_private_field_values(tmp_path,capsys):
    path=tmp_path/'invalid.json';path.write_text('{"entries":"private-test-data"}')
    assert cli.main([str(path)])==2
    output=capsys.readouterr()
    assert 'private-test-data' not in output.out+output.err
