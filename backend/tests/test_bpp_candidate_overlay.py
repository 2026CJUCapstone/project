"""Offline containment/provenance checks; never runtime or policy acceptance."""
from copy import deepcopy
import gzip
import importlib.util
import io
from pathlib import Path
import sys
import tarfile

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import bpp_candidate_overlay as overlay
import probe_bpp_candidate as compiler_probe
spec=importlib.util.spec_from_file_location('overlay_baseline_tests',Path(__file__).with_name('test_runtime_matrix_harness.py'))
baseline_tests=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline_tests)
child_options=baseline_tests.child_options
baseline_probe=baseline_tests.probe


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    data=b'\x7fELFsynthetic-test-only'
    archive=tmp_path/'compiler.tar.gz'
    with tarfile.open(archive,'w:gz') as stream:
        for name,value in {'src/std/io.bpp':b'std','src/main.bpp':b'compiler','config.ini':b'config'}.items():
            item=tarfile.TarInfo(name);item.size=len(value);stream.addfile(item,io.BytesIO(value))
    monkeypatch.setattr(overlay,'ARCHIVE_SHA',overlay.digest(archive.read_bytes()))
    monkeypatch.setattr(compiler_probe,'ARCHIVE_SHA',overlay.ARCHIVE_SHA)
    monkeypatch.setattr(overlay,'STAGE2_SHA',overlay.digest(data))
    (tmp_path/'candidate-stage2.gz').write_bytes(gzip.compress(data))
    identity=overlay.prepare_overlay(tmp_path)
    return tmp_path,identity


def test_prepared_overlay_has_exact_fixed_source_binary_identity(prepared):
    root,identity=prepared
    assert overlay.overlay_identity(root)==identity
    assert identity['binarySha256']==overlay.STAGE2_SHA
    assert identity['sourceArchiveSha256']==overlay.ARCHIVE_SHA
    assert identity['imageAccepted'] is False
    assert identity['kind']=='isolated-readonly-candidate-overlay'


@pytest.mark.parametrize('target',['compiler','compiler.tar.gz','source/src/std/io.bpp'])
def test_modified_overlay_fails_before_container_creation(prepared,target):
    root,_=prepared;path=root/'bpp-candidate'/target;path.chmod(0o644);path.write_bytes(b'corrupt')
    options=child_options(root/'work','bpp')
    with pytest.raises(ValueError): overlay.attach_overlay(options,root,overlay.IMAGE)


def test_extra_standard_library_file_is_not_authorized(prepared):
    root,_=prepared;std=root/'bpp-candidate/source/src/std';std.chmod(0o755)
    (std/'extra.bpp').write_bytes(b'unreviewed')
    with pytest.raises(ValueError,match='differs'): overlay.overlay_identity(root)


def test_standard_library_ancestor_symlink_is_rejected(prepared,monkeypatch):
    root,_=prepared;original=Path.is_symlink
    ancestor=root/'bpp-candidate/source'
    monkeypatch.setattr(Path,'is_symlink',lambda path:path==ancestor or original(path))
    with pytest.raises(ValueError,match='Symlink'): overlay.overlay_identity(root)


def test_compile_only_overlay_preserves_all_base_isolation_and_argv(prepared):
    root,_=prepared;work=root/'work'
    options=child_options(work,'bpp');options['image']=overlay.IMAGE
    baseline_probe.verify_child_options(options,work,overlay.IMAGE,'test-owner')
    original=deepcopy(options)
    updated=overlay.attach_overlay(options,root,overlay.IMAGE)
    assert options==original
    assert {k:v for k,v in updated.items() if k!='volumes'}=={k:v for k,v in original.items() if k!='volumes'}
    additions={k:v for k,v in updated['volumes'].items() if k not in original['volumes']}
    assert additions=={
        str(root/'bpp-candidate/compiler'):{'bind':overlay.BINARY_TARGET,'mode':'ro'},
        str(root/'bpp-candidate/source/src/std'):{'bind':overlay.STD_TARGET,'mode':'ro'},
    }
    # Ordinary image verification must still reject arbitrary extra mounts.
    with pytest.raises(RuntimeError,match='mount'): baseline_probe.verify_child_options(updated,work,overlay.IMAGE,'test-owner')
    run=child_options(work,'bpp','run')
    assert overlay.attach_overlay(run,root,overlay.IMAGE) is run


@pytest.mark.parametrize('corruption',['none','rw','extra','cap','run-overlay'])
def test_final_options_are_revalidated_after_injection(prepared,corruption):
    root,_=prepared;work=root/'work'
    phase='run' if corruption=='run-overlay' else 'compile'
    options=child_options(work,'bpp',phase);options['image']=overlay.IMAGE
    options=overlay.attach_overlay(options,root,overlay.IMAGE)
    if corruption=='rw': options['volumes'][str(root/'bpp-candidate/compiler')]['mode']='rw'
    if corruption=='extra': options['volumes'][str(root/'extra')]={'bind':'/extra','mode':'ro'}
    if corruption=='cap': options['cap_add'].append('SYS_ADMIN')
    if corruption=='run-overlay': options['volumes'][str(root/'bpp-candidate/compiler')]={'bind':overlay.BINARY_TARGET,'mode':'ro'}
    if corruption=='none':
        assert overlay.verify_overlay_options(options,work,overlay.IMAGE,'test-owner')['overlayApplied'] is True
    else:
        with pytest.raises((ValueError,RuntimeError)): overlay.verify_overlay_options(options,work,overlay.IMAGE,'test-owner')


def test_run_records_the_exact_candidate_compiled_artifact(prepared):
    root,_=prepared;work=root/'work';artifact=work/'job/source';artifact.mkdir(parents=True)
    (artifact/'program').write_bytes(b'candidate program')
    options=child_options(work,'bpp','run');options['image']=overlay.IMAGE
    row=overlay.verify_overlay_options(options,work,overlay.IMAGE,'test-owner')
    assert row==dict(phase='run',overlayApplied=False,readOnlyTargets=[],
        execution='candidate-compiled/base-image-executed',artifactSha256=overlay.digest(b'candidate program'))


def test_overlay_manifest_binds_base_identity_without_approving_image(prepared):
    _,identity=prepared
    installed=dict(version='binary-sha256:'+'a'*64,launcherSha256='b'*64)
    value=overlay.bind_base_identity(identity,overlay.IMAGE,installed)
    assert value['imageAccepted'] is False and value['installedBinaryVersion']==installed['version']
    assert value['binarySha256']==overlay.STAGE2_SHA
    changed=overlay.bind_base_identity(identity,overlay.IMAGE,{**installed,'launcherSha256':'c'*64})
    assert changed['manifestSha256']!=value['manifestSha256']
    with pytest.raises(ValueError): overlay.bind_base_identity(identity,'wrong-image',installed)


@pytest.mark.parametrize('fault',['none','artifact','manifest','run-overlay','missing','name'])
def test_per_phase_provenance_must_match_the_compile(fault):
    bindings=[dict(phase='compile',overlayApplied=True,readOnlyTargets=[overlay.BINARY_TARGET,overlay.STD_TARGET],containerName='compile',manifestSha256='m'),
        dict(phase='run',overlayApplied=False,readOnlyTargets=[],containerName='case',manifestSha256='m',artifactSha256='a',execution='candidate-compiled/base-image-executed')]
    if fault=='artifact': bindings[1]['artifactSha256']='other'
    if fault=='manifest': bindings[0]['manifestSha256']='other'
    if fault=='run-overlay': bindings[1]['overlayApplied']=True
    if fault=='missing': bindings.pop()
    if fault=='name': bindings[1]['containerName']='other'
    if fault=='none': overlay.verify_bindings(bindings,['compile','case'],'m','a')
    else:
        with pytest.raises(ValueError): overlay.verify_bindings(bindings,['compile','case'],'m','a')


@pytest.mark.parametrize('violation',['wrong-image','wrong-language','mount-target','mount-source'])
def test_overlay_rejects_scope_and_mount_collisions(prepared,violation):
    root,_=prepared;options=child_options(root/'work','python' if violation=='wrong-language' else 'bpp')
    if violation=='mount-target': options['volumes']['/other']={'bind':overlay.BINARY_TARGET,'mode':'ro'}
    if violation=='mount-source': options['volumes'][str(root/'bpp-candidate/compiler')]={'bind':'/other','mode':'ro'}
    with pytest.raises(ValueError):
        overlay.attach_overlay(options,root,'wrong' if violation=='wrong-image' else overlay.IMAGE)


def test_installed_image_aggregator_cannot_count_candidate_as_plain_image(tmp_path):
    import json
    from summarize_freshman_measurements import summarize
    report=tmp_path/'report.json'
    report.write_text(json.dumps(dict(suite='freshman-candidate',timedOut=False,controllerExitCode=0)))
    with pytest.raises(ValueError,match='Incomplete'): summarize([report])
