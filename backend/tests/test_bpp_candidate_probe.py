"""Offline fixed-source extraction and bounded build failure checks."""
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import probe_bpp_candidate as probe
import run_isolated_bpp_candidate as host_probe


@pytest.mark.parametrize('name,kind',[('../outside','file'),('/outside','file'),('bin/unknown','file'),
    ('src/link','symlink')])
def test_candidate_archive_rejects_unsafe_members_even_if_hash_matches(monkeypatch,tmp_path,name,kind):
    archive=tmp_path/'source.tar.gz'
    with tarfile.open(archive,'w:gz') as stream:
        member=tarfile.TarInfo(name)
        if kind=='symlink': member.type=tarfile.SYMTYPE;member.linkname='/outside'
        else: member.size=1
        stream.addfile(member,io.BytesIO(b'x'))
    monkeypatch.setattr(probe,'ARCHIVE_SHA',probe.sha(archive))
    with pytest.raises(ValueError): probe.extract_candidate(archive,tmp_path/'extract')


def test_candidate_archive_requires_exact_reviewed_bytes(tmp_path):
    archive=tmp_path/'source.tar.gz';archive.write_bytes(b'wrong')
    with pytest.raises(ValueError,match='Unreviewed'): probe.extract_candidate(archive,tmp_path/'extract')


def test_frontend_phase_stops_before_assembly_and_preserves_own_source():
    argv=probe.frontend_argv(Path('/raw/compiler'),Path('/candidate/src/main.bpp'))
    assert argv==[str(Path('/raw/compiler')),'-dump-ast','--ast-no-std','--ast-func','main',str(Path('/candidate/src/main.bpp'))]
    assert '-asm' not in argv and '-O1' not in argv
    assert probe.BASELINE_SHA!=probe.ARCHIVE_SHA and probe.BASELINE_COMMIT!=probe.COMMIT


def test_reduction_changes_only_import_not_compiler_archive_or_cli():
    controls=probe.frontend_reductions()
    assert controls==[('empty','func main() -> u64 { return 0; }\n'),
        ('annotations','import compiler.annotations;\nfunc main() -> u64 { return 0; }\n')]
    assert len(controls)==2  # At most two 100-CPU-second phases under the 240s outer cap.
    assert 'frontend-reduction' in probe.MODES


def test_single_stage_budget_is_explicit_and_does_not_relax_other_modes():
    assert host_probe.probe_budget('stage0') == dict(memory='1g',timeout=760,minimumAvailable=4*1024**3)
    assert host_probe.probe_budget('fixedpoint') == dict(memory='1g',timeout=1500,minimumAvailable=4*1024**3)
    for mode in ('selfhost','frontend','frontend-reduction','regressions'):
        assert host_probe.probe_budget(mode) == dict(memory='512m',timeout=240,minimumAvailable=2*1024**3)
    with pytest.raises(ValueError): host_probe.probe_budget('unlimited')


def test_candidate_regressions_reject_wrong_binary_before_loading_gate(monkeypatch,tmp_path):
    original=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda path: b'wrong' if str(path).replace('\\','/')=='/input/stage0' else original(path))
    with pytest.raises(ValueError,match='Unreviewed stage0'):
        probe.candidate_regressions(tmp_path)


def test_candidate_reference_sources_remain_exact():
    base=Path(__file__).resolve().parents[2]
    for name,digest in probe.REFERENCE_SHA.items():
        assert probe.sha(base/'tools/freshman_contest/solutions/bpp'/(name+'.bpp'))==digest


@pytest.mark.parametrize('data',[b'wrong',b'\x7fELFwrong'])
def test_fixed_point_never_accepts_an_unverified_bootstrap(tmp_path,data):
    binary=tmp_path/'candidate';binary.write_bytes(data)
    with pytest.raises(ValueError,match='Unreviewed stage0'):
        probe.verified_stage0(binary)


@pytest.mark.parametrize('asm_equal,binary_equal',[(True,True),(True,False),(False,True),(False,False)])
def test_fixed_point_requires_both_assembly_and_executable_identity(tmp_path,asm_equal,binary_equal):
    for name,data in {'stage1':b'one','stage2':b'one' if binary_equal else b'two',
                     'stage1.asm':b'asm','stage2.asm':b'asm' if asm_equal else b'other'}.items():
        (tmp_path/name).write_bytes(data)
    assert probe.fixed_point(tmp_path,tmp_path)==dict(fixedPoint=binary_equal,assemblyFixedPoint=asm_equal)


def test_canonical_nasm_path_preserves_both_original_stage_artifacts(tmp_path):
    sources=[tmp_path/'stage1.asm',tmp_path/'stage2.asm']
    for source in sources: source.write_bytes(b'exact assembly')
    paths=[probe.canonical_assembly(source,tmp_path) for source in sources]
    assert paths==[tmp_path/'native.asm']*2
    assert all(source.read_bytes()==b'exact assembly' for source in [*sources,*paths])


@pytest.mark.parametrize('failure',[False,True,'timeout'])
def test_build_records_failures_and_never_silently_promotes(monkeypatch,tmp_path,failure):
    if sys.platform=='win32':
        monkeypatch.setitem(sys.modules,'resource',SimpleNamespace(RUSAGE_CHILDREN=-1,
            getrusage=lambda _:SimpleNamespace(ru_utime=0,ru_stime=0)))
    def run(argv,**kwargs):
        assert kwargs['timeout']==5 and kwargs['preexec_fn'] is probe.child_limits
        assert kwargs['cwd']==tmp_path and kwargs['stdin']==subprocess.DEVNULL
        kwargs['stderr'].write(b'diagnostic')
        if failure=='timeout': raise subprocess.TimeoutExpired(argv,5)
        kwargs['stdout'].write(b'assembly')
        return SimpleNamespace(returncode=1 if failure else 0)
    monkeypatch.setattr(probe.subprocess,'run',run)
    rows=[]
    if failure:
        with pytest.raises(RuntimeError): probe.build_phase(rows,tmp_path,'compile',['fixed','-asm'],tmp_path/'out',5)
    else: probe.build_phase(rows,tmp_path,'compile',['fixed','-asm'],tmp_path/'out',5)
    assert len(rows)==1 and rows[0]['diagnostic']=='diagnostic'
    assert rows[0]['stdoutSha256']==hashlib.sha256((tmp_path/'out').read_bytes()).hexdigest()
    if failure=='timeout': assert rows[0]['timedOut'] is True
