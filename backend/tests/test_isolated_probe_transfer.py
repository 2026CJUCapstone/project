"""Offline transport checks; never contacts SSH or writes remote paths."""
from pathlib import Path
import gzip
import hashlib
import shlex
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import transfer_isolated_probe as transfer
import probe_bpp_candidate as candidate


@pytest.mark.parametrize('root,name', [('/tmp','probe'),('/tmp/webcompiler-launcher-test.x/../y','probe'),
    ('/tmp/webcompiler-launcher-test.x','../bad'),('/tmp/webcompiler-launcher-test.x','bad;cmd')])
def test_invalid_transfer_destination_never_calls_ssh(monkeypatch,root,name):
    monkeypatch.setattr(transfer.subprocess,'run',lambda *a,**kw: pytest.fail('unexpected SSH'))
    with pytest.raises(ValueError): transfer.upload_bytes(root,b'x',name)


def test_chunked_transfer_keeps_binary_identity_and_exclusive_destination(monkeypatch,tmp_path):
    calls=[]
    monkeypatch.setattr(transfer.subprocess,'run',lambda *a,**kw: calls.append((a,kw)))
    data=bytes(range(256))*70
    source=tmp_path/'probe';source.write_bytes(data)
    transfer.upload('/tmp/webcompiler-launcher-test.test',source,'archive.gz')
    assert len(calls)==4
    assert b''.join(kw['input'] for _,kw in calls[:-1])==data
    assert all(len(kw['input'])<=8192 for _,kw in calls[:-1])
    for args,kw in calls:
        remote=shlex.split(args[0][-1])
        compile(remote[2],'<remote>','exec')
        assert "open('xb')" in remote[2]
        assert kw['timeout']==30 and kw['check'] is True
        assert not kw.get('shell',False)
    assert 'input' not in calls[-1][1]


def test_candidate_transfer_is_fixed_to_reviewed_reference_inputs():
    root=Path(__file__).resolve().parents[2]
    files=transfer.fixed_inputs(root,draft=True,candidate=True)
    assert files['freshman-package.tar.gz']==root/'.deploy/freshman-measurement-package-draft-v2.tar.gz'
    assert files['compiler.tar.gz']==root/'.deploy/bpp-candidate-9859a2d-src.tar.gz'
    assert files['candidate-stage2.gz']==root/'.deploy/bpp-candidate-9859a2d-stage2.gz'
    missing = [name for name in ('compiler.tar.gz', 'candidate-stage2.gz') if not files[name].is_file()]
    if missing:
        pytest.skip('B++ candidate archives are external staged artifacts: ' + ', '.join(missing))
    assert hashlib.sha256(files['compiler.tar.gz'].read_bytes()).hexdigest()==candidate.ARCHIVE_SHA
    assert hashlib.sha256(gzip.decompress(files['candidate-stage2.gz'].read_bytes())).hexdigest()==candidate.STAGE2_SHA
    assert set(files)-set(transfer.fixed_inputs(root,draft=True))=={
        'compiler.tar.gz','candidate-stage2.gz','bpp_candidate_overlay.py','probe_bpp_candidate.py'}
    assert transfer.fixed_inputs(root,candidate=True)['freshman-package.tar.gz']==root/'.deploy/freshman-measurement-package-v1.tar.gz'
    with pytest.raises(ValueError): transfer.fixed_inputs(root,draft=True,slow=True,candidate=True)


def test_transfer_selects_the_archive_matching_each_reference_suite():
    root=Path(__file__).resolve().parents[2]
    assert transfer.fixed_inputs(root)['freshman-package.tar.gz']==root/'.deploy/freshman-measurement-package-v1.tar.gz'
    assert transfer.fixed_inputs(root,draft=True)['freshman-package.tar.gz']==root/'.deploy/freshman-measurement-package-draft-v2.tar.gz'
    assert transfer.fixed_inputs(root,draft=True,slow=True)['freshman-package.tar.gz']==root/'.deploy/freshman-measurement-package-draft-v2-slow.tar.gz'
