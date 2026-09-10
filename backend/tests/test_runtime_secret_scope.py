"""Credential input cannot change the verified deployment scope or run shell."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import re

import pytest


ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('audit_runtime_secrets',ROOT/'scripts/runtime_secrets.py')
secrets=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(secrets)


def secret_file(tmp_path,text):
    path=tmp_path/'runtime-secrets.env'
    path.write_text(text,encoding='utf-8')
    path.chmod(0o600)
    return path


@pytest.mark.parametrize('key',['PROJECT_ROOT','SOURCE_ROOT','DEPLOY_SHA','PATH','BASH_ENV',
    'WEBCOMPILER_PROJECT_PREFIX','WEBCOMPILER_BACKEND_IMAGE','SANDBOX_POOL_ID',
    'WEBCOMPILER_SHARED_POSTGRES_NAME','WEBCOMPILER_SHARED_POSTGRES_VOLUME',
    'WEBCOMPILER_SHARED_POSTGRES_NETWORK','WEBCOMPILER_SHARED_REDIS_NAME',
    'WEBCOMPILER_SHARED_REDIS_VOLUME','WEBCOMPILER_REDIS_URL','WEBCOMPILER_REDIS_KEY_PREFIX',
    'WEBCOMPILER_EDGE_BACKEND_PORT','WEBCOMPILER_FRONTEND_EDGE_NAME','WEBCOMPILER_LEGACY_PROJECT_NAME'])
def test_scope_keys_rejected_without_exposing_input(tmp_path,key):
    path=secret_file(tmp_path,'WEBCOMPILER_SECRET_KEY=private-sentinel\n'+key+'=sensitive-scope-sentinel\n')
    with pytest.raises(secrets.RuntimeSecretsError) as error: secrets.load(path)
    assert 'private-sentinel' not in str(error.value) and 'sensitive-scope-sentinel' not in str(error.value)


@pytest.mark.parametrize('text',['WEBCOMPILER_SECRET_KEY=a\nWEBCOMPILER_SECRET_KEY=b',
    'WEBCOMPILER_SECRET_KEY=a; touch sentinel','source other.env','WEBCOMPILER_SECRET_KEY="unfinished',
    'WEBCOMPILER_SECRET_KEY=abc\0def','x'*65537],
    ids=['duplicate','shell-command','source','quote','nul','oversized'])
def test_malformed_file_is_not_partially_accepted(tmp_path,text):
    with pytest.raises(secrets.RuntimeSecretsError): secrets.load(secret_file(tmp_path,text))


def test_missing_is_only_allowed_during_initial_validation(tmp_path):
    path=tmp_path/'missing.env'
    assert secrets.load(path,allow_missing=True)=={}
    with pytest.raises(secrets.RuntimeSecretsError): secrets.load(path)


@pytest.mark.skipif(os.name!='posix',reason='POSIX credential file permissions')
def test_public_file_or_symlink_is_rejected(tmp_path):
    path=secret_file(tmp_path,'WEBCOMPILER_POSTGRES_PASSWORD=only-fixture')
    path.chmod(0o644)
    with pytest.raises(secrets.RuntimeSecretsError): secrets.load(path)
    path.chmod(0o600)
    link=tmp_path/'link.env'
    link.symlink_to(path)
    with pytest.raises(secrets.RuntimeSecretsError): secrets.load(link)


@pytest.mark.skipif(os.name!='posix',reason='Actual POSIX FIFO rejection')
def test_fifo_is_rejected_without_waiting_for_a_writer(tmp_path):
    path=tmp_path/'credentials.fifo'
    os.mkfifo(path,0o600)
    result=subprocess.run([sys.executable,str(ROOT/'scripts/runtime_secrets.py'),'validate','--file',str(path)],
        capture_output=True,text=True,timeout=3)
    assert result.returncode==1
    assert result.stdout=='' and 'Runtime secrets rejected' in result.stderr


@pytest.mark.skipif(os.name!='posix' or not shutil.which('bash'),reason='Actual deployment secret initialization')
def test_deploy_initialization_preserves_exported_and_quoted_existing_secrets(tmp_path):
    path=secret_file(tmp_path,"  export WEBCOMPILER_SECRET_KEY='"+'k'*32+"'\nWEBCOMPILER_ADMIN_PASSWORD="+'a'*16+'\n')
    original=path.read_bytes()
    result=subprocess.run([sys.executable,str(ROOT/'scripts/runtime_secrets.py'),'ensure','--file',str(path)],
        capture_output=True,text=True,timeout=5,
        env={'PATH':os.environ['PATH'],'WEBCOMPILER_POSTGRES_PASSWORD':'operator-fixture-password-24'})
    assert result.returncode==0,result.stderr
    assert result.stdout==''
    assert path.read_bytes()==original


@pytest.mark.skipif(os.name!='posix' or not shutil.which('bash'),reason='Actual deployment secret initialization')
def test_deploy_initialization_adds_only_missing_generated_credentials(tmp_path):
    path=secret_file(tmp_path,"export WEBCOMPILER_SECRET_KEY='"+'k'*32+"'\nWEBCOMPILER_POSTGRES_PASSWORD=operator-fixture-password-24\n")
    env={'PATH':os.environ['PATH']}
    for _ in range(2):
        result=subprocess.run([sys.executable,str(ROOT/'scripts/runtime_secrets.py'),'ensure','--file',str(path)],
            capture_output=True,text=True,timeout=5,env=env)
        assert result.returncode==0,result.stderr
        assert result.stdout==''
        values=secrets.load(path)
        assert values['WEBCOMPILER_SECRET_KEY']=='k'*32
        assert values['WEBCOMPILER_POSTGRES_PASSWORD']=='operator-fixture-password-24'
        assert re.fullmatch(r'[A-Za-z0-9_-]{43}',values['WEBCOMPILER_ADMIN_PASSWORD'])
        if _==0: first=path.read_bytes()
        else: assert path.read_bytes()==first


@pytest.mark.skipif(os.name!='posix' or not shutil.which('bash'),reason='Actual POSIX shell quoting')
def test_generated_exports_cannot_execute_credential_content(tmp_path):
    marker=tmp_path/'must-not-exist'
    value='$(touch '+str(marker)+'); `touch '+str(marker)+'` \' " $HOME # literal'
    path=secret_file(tmp_path,'SMTP_PASSWORD='+secrets.shlex.quote(value)+'\n')
    loaded=secrets.load(path)
    payload=secrets.exports(loaded)
    result=subprocess.run(['bash','-c','set -eu\neval "$1"\nprintf "%s" "$SMTP_PASSWORD"','bash',payload],
        capture_output=True,text=True,timeout=5,env={'PATH':os.environ['PATH']})
    assert result.returncode==0 and result.stdout==value
    assert not marker.exists()


def test_deploy_validates_secret_file_before_prepare_and_never_sources_it():
    source=(ROOT/'scripts/deploy_server.sh').read_text()
    validate=source.index('scripts/runtime_secrets.py" validate --deployment --allow-missing')
    assert validate<source.index('scripts/edge_deploy.py" preflight')<source.index('scripts/edge_deploy.py" prepare')
    assert source.index('scripts/runtime_secrets.py" ensure')<source.index('scripts/edge_deploy.py" prepare')
    assert '>> "$RUNTIME_SECRETS_FILE"' not in source
    assert 'chmod 600 "$RUNTIME_SECRETS_FILE"' not in source
    assert 'source "$RUNTIME_SECRETS_FILE"' not in source
    emit=source.index('runtime_secret_exports="$(python3')
    assert emit<source.index('eval "$runtime_secret_exports"')<source.index('scripts/edge_deploy.py" prepare')
    assert 'runtime_secrets.py" exports' not in source
    assert 'unset runtime_secret_exports' in source


@pytest.mark.parametrize('values',[
    {},{'WEBCOMPILER_POSTGRES_PASSWORD':''},{'WEBCOMPILER_POSTGRES_PASSWORD':'short'},
    {'WEBCOMPILER_POSTGRES_PASSWORD':'x'*24,'SECRET_KEY':'short'},
    {'WEBCOMPILER_POSTGRES_PASSWORD':'x'*24,'WEBCOMPILER_ADMIN_PASSWORD':''},
    {'WEBCOMPILER_POSTGRES_PASSWORD':'x'*24,'ADMIN_PASSWORD':'short','WEBCOMPILER_ADMIN_PASSWORD':'a'*32},
])
def test_deployment_rejects_missing_or_weak_effective_credentials(values):
    with pytest.raises(secrets.RuntimeSecretsError): secrets.validate_deployment(values,{})


def test_deployment_uses_file_override_and_raw_alias_precedence():
    secrets.validate_deployment({'WEBCOMPILER_POSTGRES_PASSWORD':'p'*24,'SECRET_KEY':'s'*32},
        {'WEBCOMPILER_POSTGRES_PASSWORD':'invalid','WEBCOMPILER_SECRET_KEY':'short'})
    with pytest.raises(secrets.RuntimeSecretsError):
        secrets.validate_deployment({'WEBCOMPILER_POSTGRES_PASSWORD':''},
            {'WEBCOMPILER_POSTGRES_PASSWORD':'p'*24})


@pytest.mark.parametrize('value',["'"*1000,'a'*32+'\nnext-line'],ids=['quoted-line-bound','multiline'])
def test_environment_credential_must_roundtrip_supported_literal_format(value):
    with pytest.raises(secrets.RuntimeSecretsError):
        secrets.validate_deployment({}, {'WEBCOMPILER_POSTGRES_PASSWORD':'p'*24,'SECRET_KEY':value})


@pytest.mark.skipif(os.name!='posix',reason='Actual checked descriptor initialization')
@pytest.mark.parametrize('replacement',['symlink','public-file','private-file'])
def test_ensure_rejects_path_swap_before_write_without_changing_target(tmp_path,monkeypatch,replacement):
    path=secret_file(tmp_path,'WEBCOMPILER_POSTGRES_PASSWORD='+'p'*24+'\n')
    target=tmp_path/'unrelated.env'
    target.write_text('DO_NOT_CHANGE\n')
    original=path.read_bytes()
    real_read=secrets.read_private
    reads=0
    def swap_after_descriptor_read(source):
        nonlocal reads
        result=real_read(source)
        reads+=1
        if reads==2:
            path.rename(tmp_path/'original.env')
            if replacement=='symlink': path.symlink_to(target)
            else:
                path.write_bytes(original)
                path.chmod(0o644 if replacement=='public-file' else 0o600)
        return result
    monkeypatch.setattr(secrets,'read_private',swap_after_descriptor_read)
    with pytest.raises(secrets.RuntimeSecretsError): secrets.ensure(path,{})
    assert target.read_text()=='DO_NOT_CHANGE\n'
    assert (tmp_path/'original.env').read_bytes()==original
    if replacement!='symlink': assert path.read_bytes()==original


@pytest.mark.skipif(os.name!='posix',reason='Actual credential initialization')
def test_missing_postgres_credential_cannot_create_secret_file(tmp_path):
    path=tmp_path/'missing.env'
    with pytest.raises(secrets.RuntimeSecretsError): secrets.ensure(path,{})
    assert not path.exists()


@pytest.mark.skipif(os.name!='posix',reason='Actual post-write identity verification')
def test_path_swap_during_fsync_cannot_return_or_export_replacement(tmp_path,monkeypatch):
    path=secret_file(tmp_path,'WEBCOMPILER_POSTGRES_PASSWORD='+'p'*24+'\n')
    replacement=b'WEBCOMPILER_POSTGRES_PASSWORD=weak\n'
    real_sync=secrets.os.fsync
    def swap(fd):
        real_sync(fd)
        path.rename(tmp_path/'old-private.env')
        path.write_bytes(replacement)
        path.chmod(0o600)
    monkeypatch.setattr(secrets.os,'fsync',swap)
    with pytest.raises(secrets.RuntimeSecretsError): secrets.ensure(path,{})
    assert path.read_bytes()==replacement


@pytest.mark.skipif(os.name!='posix',reason='Actual parent directory binding')
def test_parent_symlink_is_not_followed_for_load_or_initialization(tmp_path):
    target=tmp_path/'target'
    target.mkdir()
    path=secret_file(target,'WEBCOMPILER_POSTGRES_PASSWORD='+'p'*24+'\n')
    original=path.read_bytes()
    link=tmp_path/'linked'
    link.symlink_to(target,target_is_directory=True)
    for action in (lambda:secrets.load(link/path.name),lambda:secrets.ensure(link/path.name,{})):
        with pytest.raises((secrets.RuntimeSecretsError,OSError)): action()
    assert path.read_bytes()==original


@pytest.mark.skipif(os.name!='posix',reason='Actual parent directory binding')
def test_parent_replacement_during_write_cannot_return_credentials(tmp_path,monkeypatch):
    parent=tmp_path/'private'
    parent.mkdir()
    path=secret_file(parent,'WEBCOMPILER_POSTGRES_PASSWORD='+'p'*24+'\n')
    real_sync=secrets.os.fsync
    def swap(fd):
        real_sync(fd)
        parent.rename(tmp_path/'old-parent')
        parent.mkdir()
        secret_file(parent,'WEBCOMPILER_POSTGRES_PASSWORD=do-not-adopt\n')
    monkeypatch.setattr(secrets.os,'fsync',swap)
    with pytest.raises(secrets.RuntimeSecretsError): secrets.ensure(path,{})
    assert path.read_text()=='WEBCOMPILER_POSTGRES_PASSWORD=do-not-adopt\n'


@pytest.mark.skipif(os.name!='posix',reason='Actual operator credential initialization')
@pytest.mark.parametrize('prefix',['','WEBCOMPILER_'])
def test_supplied_environment_credentials_are_preserved_not_regenerated(tmp_path,prefix):
    path=tmp_path/'new.env'
    key="operator-key-with-'quotes'-and-$dollars"
    password='operator admin password with spaces'
    values=secrets.ensure(path,{'WEBCOMPILER_POSTGRES_PASSWORD':'p'*24,
        prefix+'SECRET_KEY':key,prefix+'ADMIN_PASSWORD':password})
    assert values['WEBCOMPILER_SECRET_KEY']==key
    assert values['WEBCOMPILER_ADMIN_PASSWORD']==password
    assert secrets.load(path)==values
