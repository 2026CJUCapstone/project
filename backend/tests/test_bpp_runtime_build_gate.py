"""Build-gate orchestration tests, not proof of a repaired Linux compiler."""
import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('bpp_gate',ROOT/'runtime/sandbox/verify_bpp_runtime.py')
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)


@pytest.mark.parametrize('failure',[None,'compile','assemble','link','run','wrong-output','timeout','missing-tool'])
def test_gate_fails_closed_at_each_stage(monkeypatch,tmp_path,failure):
    calls=[]
    def run(argv,**kwargs):
        phase=('compile','assemble','link','run')[len(calls)];calls.append((argv,kwargs))
        if failure=='timeout': raise subprocess.TimeoutExpired(argv,kwargs['timeout'])
        if failure=='missing-tool': raise FileNotFoundError()
        stdout=b'assembly' if phase=='compile' else b'42\n' if phase=='run' else b''
        if phase=='run' and failure=='wrong-output': stdout=b'43\n'
        return SimpleNamespace(returncode=1 if failure==phase else 0,stdout=stdout,stderr=b'error')
    monkeypatch.setattr(gate.subprocess,'run',run)
    source,expected=gate.CASES['large-local-frame']
    row=gate.check_case(tmp_path,'large-local-frame',source,expected)
    assert row['passed'] is (failure is None)
    assert all(kw['input']==b'' and kw['timeout']<=15 and not kw.get('shell') for _,kw in calls)
    assert calls[0][0][:3]==['bpp','-O1','-asm']
    assert Path(calls[0][0][3]).stem.isidentifier()
    if failure in ('compile','assemble','link','run'): assert row['phase']==failure


def test_gate_checks_both_regressions_and_is_mandatory_after_user_switch(monkeypatch,capsys):
    seen=[]
    def check(root,name,*args):
        seen.append(name);return dict(name=name,passed=name!='large-local-frame')
    monkeypatch.setattr(gate,'check_case',check)
    assert gate.main()==1
    assert set(seen)=={'large-local-frame','pointer-parameter-gc'}
    assert 'performance approval' in capsys.readouterr().out
    dockerfile=(ROOT/'runtime/docker/Dockerfile').read_text()
    assert dockerfile.index('USER sandboxuser')<dockerfile.index('RUN python3 -I /usr/local/share/verify_bpp_runtime.py')
    assert 'var values: [8192]u8' in gate.CASES['large-local-frame'][0]
    assert 'clobber()' in gate.CASES['large-local-frame'][0]
    for script in ('build_sandbox_image.sh','update_sandbox_image_if_needed.sh'):
        assert '"$PROJECT_ROOT/runtime/sandbox/verify_bpp_runtime.py"' in (ROOT/'scripts'/script).read_text()


def test_candidate_path_and_reference_input_do_not_change_installed_default(monkeypatch,tmp_path):
    calls=[]
    def run(argv,**kwargs):
        calls.append((argv,kwargs))
        return SimpleNamespace(returncode=0,stdout=b'assembly' if len(calls)==1 else b'5\n' if len(calls)==4 else b'',stderr=b'')
    monkeypatch.setattr(gate.subprocess,'run',run)
    assert gate.check_case(tmp_path,'reference_J','source',b'5\n',compiler='/input/stage0',stdin=b'3\n-5 4 3\n')['passed']
    assert calls[0][0]==['/input/stage0','-O1','-asm',str(tmp_path/'reference_J.bpp')]
    assert [kwargs['input'] for _,kwargs in calls]==[b'',b'',b'',b'3\n-5 4 3\n']


@pytest.mark.parametrize(
    ('optimization','ssa','expected_flags'),
    [
        ('O0',False,['-O0','-asm']),
        ('O1',False,['-O1','-asm']),
        ('O1',True,['-O1','-dump-ssa','-asm']),
    ],
)
def test_stage0_gate_validates_native_optimization_and_ssa_flag_order(monkeypatch,tmp_path,optimization,ssa,expected_flags):
    calls=[]
    def run(argv,**kwargs):
        calls.append((argv,kwargs))
        phase=('compile','assemble','link','run')[len(calls)-1]
        stdout=b'assembly' if phase=='compile' else b'42\n' if phase=='run' else b''
        return SimpleNamespace(returncode=0,stdout=stdout,stderr=b'')
    monkeypatch.setattr(gate.subprocess,'run',run)

    row=gate.check_case(
        tmp_path,'large-local-frame','source',b'42\n',compiler='/input/stage0',
        optimization=optimization,ssa=ssa,
    )

    assert row['passed']
    assert calls[0][0]==[
        '/input/stage0',*expected_flags,str(tmp_path/'large_local_frame.bpp'),
    ]


def test_stage0_gate_rejects_unsupported_optimization_before_subprocess(monkeypatch,tmp_path):
    calls=[]
    def run(argv,**kwargs):
        calls.append((argv,kwargs))
        pytest.fail('unsupported optimization must not invoke a subprocess')
    monkeypatch.setattr(gate.subprocess,'run',run)

    with pytest.raises(ValueError,match='optimization'):
        gate.check_case(tmp_path,'large-local-frame','source',b'42\n',optimization='O2')
    assert calls==[]


@pytest.mark.parametrize(
    'assembly',
    [
        b'assembly without the cleanup symbol\n',
        b'std_mem__bpp_gc_root_slot_remove_extra:\n',
    ],
    ids=['missing-gc-label','similarly-named-gc-label'],
)
def test_pointer_gc_gate_requires_exact_cleanup_symbol_line(monkeypatch,tmp_path,assembly):
    calls=[]
    def run(argv,**kwargs):
        calls.append((argv,kwargs))
        return SimpleNamespace(returncode=0,stdout=assembly,stderr=b'')
    monkeypatch.setattr(gate.subprocess,'run',run)
    source,expected=gate.CASES['pointer-parameter-gc']

    row=gate.check_case(tmp_path,'pointer-parameter-gc',source,expected)

    assert row['passed'] is False
    assert row['phase']=='compile'
    assert len(calls)==1


def test_pointer_gc_gate_accepts_exact_cleanup_symbol_and_runtime_output(monkeypatch,tmp_path):
    calls=[]
    def run(argv,**kwargs):
        calls.append((argv,kwargs))
        phase=('compile','assemble','link','run')[len(calls)-1]
        stdout=(
            b'bits 64\nstd_mem__bpp_gc_root_slot_remove:\n'
            if phase=='compile' else b'42\n' if phase=='run' else b''
        )
        return SimpleNamespace(returncode=0,stdout=stdout,stderr=b'')
    monkeypatch.setattr(gate.subprocess,'run',run)
    source,expected=gate.CASES['pointer-parameter-gc']

    row=gate.check_case(tmp_path,'pointer-parameter-gc',source,expected)

    assert row['passed']
    assert len(calls)==4
    assert calls[-1][1]['input']==b''
