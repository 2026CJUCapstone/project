"""Bounded local CLI/proxy contracts; live reverse-proxy HTTP checked separately."""
import io
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError,URLError

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts import upload_judge_test_data as cli
from app.services.api_proxy_config import render,render_managed
from tests.test_edge_renderer import layout,release,render as edge_render


def test_cli_dry_run_is_offline_and_never_prints_private_bytes(tmp_path,monkeypatch,capsys):
    file=tmp_path/'input.txt';file.write_bytes('PRIVATE 한글\n'.encode())
    monkeypatch.setattr(cli,'upload_data',lambda *_:pytest.fail('unexpected upload'))
    original=cli.os.environ.get
    monkeypatch.setattr(cli.os.environ,'get',lambda name,*a:pytest.fail('credential read') if name=='CONTEST_IMPORT_TOKEN' else original(name,*a))
    assert cli.main([str(file)])==0
    output=capsys.readouterr().out
    assert json.loads(output)['mode']=='validation-only' and 'PRIVATE' not in output
    assert cli.main([str(file),'--apply'])==2


def test_cli_bounded_utf8_regular_files(tmp_path):
    file=tmp_path/'data'
    file.write_bytes(b'x'*cli.MAX_TEST_DATA_BYTES)
    assert len(cli.read_data(file))==cli.MAX_TEST_DATA_BYTES
    file.write_bytes(b'x'*(cli.MAX_TEST_DATA_BYTES+1))
    with pytest.raises(ValueError): cli.read_data(file)
    file.write_bytes(b'\xff')
    with pytest.raises(ValueError): cli.read_data(file)
    with pytest.raises(ValueError): cli.read_data(tmp_path)


class Reply(io.BytesIO):
    status=200
    headers={'Cache-Control':'no-store','Content-Encoding':'identity'}
class Transport:
    def __init__(self,result): self.result=result;self.requests=[]
    def open(self,request,timeout):
        self.requests.append((request,timeout))
        if isinstance(self.result,Exception): raise self.result
        return Reply(json.dumps(self.result).encode())


def test_cli_upload_exact_identity_bytes_and_no_automatic_retry():
    data=b'private\n';result={**cli.reference(data),'replayed':False};transport=Transport(result)
    assert cli.upload_data(data,'https://example.test/webcompiler/api/v1','secret',opener=transport)==result
    request,timeout=transport.requests[0]
    assert request.method=='PUT' and request.data==data and timeout==40
    assert request.get_header('Accept-encoding')=='identity'
    assert request.get_header('Cache-control')=='no-store'
    assert request.full_url.endswith('/admin/judge-test-data/'+result['digest'][7:]+'?byteCount=8')
    for wrong in ({**result,'digest':'sha256:'+'0'*64},{**result,'byteCount':8.0},
                  {**result,'replayed':1},{**result,'extra':'value'},URLError('secret'),
                  HTTPError('https://example.test',302,'redirect',{},None)):
        sender=Transport(wrong)
        with pytest.raises(ValueError): cli.upload_data(data,'https://example.test/api/v1','secret',opener=sender)
        assert len(sender.requests)==1
    assert cli.NoRedirect().redirect_request(None,None,302,'',{},'https://other.test') is None


@pytest.mark.parametrize('base',['http://example.test/api/v1','https://user:password@example.test/api/v1',
    'https://example.test/api/v1?x=1','file:///api/v1','https://example.test:99999/api/v1'])
def test_cli_bad_target_is_rejected_before_network(base):
    transport=Transport({})
    with pytest.raises(ValueError): cli.upload_data(b'',base,'token',opener=transport)
    assert transport.requests==[]


def upload_blocks(config):
    return re.findall(r'location \^~ /(?:webcompiler/)?api/v1/admin/judge-test-data/ \{(.*?)\n\s*\}',config,re.S)


def test_deployed_webcompiler_include_scopes_normal_api_cap_separately_from_upload():
    ingress=(ROOT/'deploy/nginx/webcompiler.locations.conf').read_text()
    normal_api=re.findall(r'(?ms)^location /webcompiler/api/ \{(.*?)^\}',ingress)
    uploads=upload_blocks(ingress)

    assert len(normal_api)==1
    assert len(uploads)==1
    assert re.findall(r'(?m)^\s*client_max_body_size\s+([^;]+);\s*$',normal_api[0])==['512k']
    assert re.findall(r'(?m)^\s*client_max_body_size\s+([^;]+);\s*$',uploads[0])==['16m']


def test_deployed_webcompiler_include_exposes_exact_health_and_ready_routes():
    ingress=(ROOT/'deploy/nginx/webcompiler.locations.conf').read_text()
    for public_path, upstream_path in (
        ('/webcompiler/health', '/health'),
        ('/webcompiler/ready', '/ready'),
    ):
        exact=f'location = {public_path} {{'
        assert ingress.count(exact)==1
        block=ingress.split(exact,1)[1].split('}',1)[0]
        assert f'proxy_pass http://127.0.0.1:18000{upstream_path};' in block


def test_proxy_caps_are_scoped_streaming_no_retry_and_membership_fenced():
    generated=render(['127.0.0.1:8000'])
    managed=render_managed(['127.0.0.1:8000'],'a'*32)
    edge=edge_render(layout(),release())
    frontend=(ROOT/'frontend/nginx.conf').read_text()
    ingress=(ROOT/'deploy/nginx/webcompiler.locations.conf').read_text()
    for config,count in ((generated,1),(managed,1),(edge,4),(frontend,2),(ingress,1)):
        blocks=upload_blocks(config)
        assert len(blocks)==count
        for block in blocks:
            assert 'client_max_body_size 16m;' in block
            assert 'proxy_request_buffering off;' in block and 'proxy_next_upstream off;' in block
            assert 'proxy_pass ' in block
            if config!=ingress:
                assert 'limit_conn judge_upload_ip 2;' in block
                assert 'limit_conn judge_upload_total 8;' in block
        assert 'client_max_body_size 512k;' in config
    block=upload_blocks(managed)[0]
    assert 'auth_request /_proxy_membership;' in block
    assert 'error_page 403 500 = @membership_unavailable;' in block
    assert '@fresh_read' not in block
