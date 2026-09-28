"""Pure validation tests. Actual Linux privilege/process tests are opt-in."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

_path=Path(__file__).resolve().parents[1]/'app/services/linux_phase_launcher.py'
_spec=importlib.util.spec_from_file_location('measured_launcher',_path)
launcher=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)


def spec():
    return dict(version=2,phase='run',argv=['/usr/bin/python3','/artifact/main.py'],stdin='/input/stdin',
        limits=dict(cpuMs=100,wallMs=200,memoryBytes=64*1024**2,outputBytes=1024,pids=16,tmpBytes=1024**2))


@pytest.mark.parametrize('name,value',[('version',True),('phase','unknown'),('argv',[]),
    ('argv',['python3']),('argv',['/usr/bin/python3','\x00']),('stdin','/etc/passwd'),('unknown',1)])
def test_spec_rejects_unbounded_or_ambiguous_inputs(name,value):
    body=spec();body[name]=value
    with pytest.raises(ValueError): launcher.validate_spec(body)


@pytest.mark.parametrize('name,value',[('cpuMs',True),('wallMs',0),('outputBytes',0),
    ('memoryBytes',2**50),('pids',1),('tmpBytes',-1),('tmpBytes',65*1024**2),('extra',1)])
def test_spec_limits_are_exact_and_no_implicit_coercion(name,value):
    body=spec();body['limits'][name]=value
    with pytest.raises(ValueError): launcher.validate_spec(body)


def test_valid_spec_keeps_absolute_values():
    body=spec();body['limits']['tmpBytes']=0
    assert launcher.validate_spec(deepcopy(body))==body


def test_non_container_never_reaches_namespace_wide_kill(monkeypatch):
    monkeypatch.setattr(launcher.os,'getpid',lambda:1234)
    monkeypatch.setattr(launcher.os,'geteuid',lambda:0,raising=False)
    monkeypatch.setattr(launcher.os,'kill',lambda *_:pytest.fail('must not signal host processes'))
    with pytest.raises(RuntimeError,match='non-container'): launcher.kill_children()
    with pytest.raises(RuntimeError,match='private Linux'): launcher.inspect_environment(spec()['limits'])


@pytest.mark.parametrize('cpu,wall,oom,pids,previous,expected',[
    (99999,199999999,0,0,None,None),
    (100000,1,0,0,None,'time_limit_exceeded'),
    (1,200000000,0,0,None,'time_limit_exceeded'),
    (1,1,1,0,None,'memory_limit_exceeded'),
    (100000,200000000,1,1,'output_limit_exceeded','memory_limit_exceeded'),
    (100000,1,0,0,'output_limit_exceeded','output_limit_exceeded'),
    (1,1,0,1,None,'process_limit_exceeded'),
    (100000,200000000,0,1,'output_limit_exceeded','process_limit_exceeded'),
])
def test_cgroup_thresholds_and_proven_oom_pid_precedence(cpu,wall,oom,pids,previous,expected):
    start=dict(cpuUsec=1000,oomKills=2,pidLimitHits=3)
    current=dict(cpuUsec=cpu+1000,oomKills=oom+2,pidLimitHits=pids+3)
    assert launcher.resource_reason(start,current,wall,spec()['limits'],previous)==expected


@pytest.mark.parametrize('current',[dict(cpuUsec=999,oomKills=2,pidLimitHits=3),
                                    dict(cpuUsec=1001,oomKills=1,pidLimitHits=3),
                                    dict(cpuUsec=1001,oomKills=2,pidLimitHits=2)])
def test_counter_reset_cannot_be_treated_as_success(current):
    with pytest.raises(RuntimeError,match='regressed'):
        launcher.resource_reason(dict(cpuUsec=1000,oomKills=2,pidLimitHits=3),current,1,spec()['limits'])


def test_missing_kernel_counters_are_not_replaced_by_zero(tmp_path):
    (tmp_path/'cpu.stat').write_text('usage_usec 100\n',encoding='ascii')
    (tmp_path/'memory.events').write_text('oom 0\noom_kill 0\n',encoding='ascii')
    with pytest.raises(FileNotFoundError): launcher.counters(tmp_path)
    (tmp_path/'memory.peak').write_text('12345\n',encoding='ascii')
    with pytest.raises(FileNotFoundError): launcher.counters(tmp_path)
    (tmp_path/'pids.events').write_text('max 0\n',encoding='ascii')
    assert launcher.counters(tmp_path)==dict(cpuUsec=100,oomKills=0,oomEvents=0,
                                              pidLimitHits=0,peakMemoryBytes=12345)


@pytest.mark.parametrize('value',['usage_usec -1\n','usage_usec 1\nusage_usec 2\n','usage_usec NaN\n'])
def test_counter_parser_rejects_ambiguous_values(tmp_path,value):
    path=tmp_path/'counter';path.write_text(value,encoding='ascii')
    with pytest.raises(ValueError): launcher.fields(path)
