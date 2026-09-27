"""A shell wrapper hash is not the native compiler's identity."""
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from run_isolated_runtime_matrix import BPP_IDENTITY_SOURCE,VERSION_PROBE


def identity():
    namespace={'hashlib':hashlib}
    exec(compile(BPP_IDENTITY_SOURCE,'<identity>','exec'),namespace)
    return namespace['bpp_identity']


def test_identity_hashes_native_elf_separately_from_launcher(tmp_path):
    wrapper=tmp_path/'bpp';wrapper.write_bytes(b'#!/bin/sh\nexec native\n')
    compiler=tmp_path/'stage1';compiler.write_bytes(b'\x7fELFfixed-native-fixture')
    result=identity()(wrapper,compiler)
    assert result['version']=='binary-sha256:'+hashlib.sha256(compiler.read_bytes()).hexdigest()
    assert result['launcherSha256']==hashlib.sha256(wrapper.read_bytes()).hexdigest()
    assert result['version']!='binary-sha256:'+result['launcherSha256']
    compile(VERSION_PROBE,'<actual-discovery>','exec')


@pytest.mark.parametrize('kind',['shell','windows','empty','oversized'])
def test_discovery_rejects_missing_non_native_or_oversized_binary(tmp_path,kind):
    content={'shell':b'#!/bin/sh\n','windows':b'MZexe','empty':b''}.get(kind)
    if content is None: content=b'\x7fELF'+b'x'*(32*1024**2)
    wrapper=tmp_path/'bpp';wrapper.write_bytes(b'wrapper')
    compiler=tmp_path/'stage1';compiler.write_bytes(content)
    with pytest.raises(RuntimeError): identity()(wrapper,compiler)
