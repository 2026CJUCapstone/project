"""Pure phase-record contract tests; these do not claim a real cgroup run."""

import json
from types import SimpleNamespace

import pytest

from app.services.judge_supervisor_record import decode_report
from app.services.judge_supervisor_records import verified_contract


LIMITS = SimpleNamespace(cpu_ms=1000, wall_ms=2000, output_bytes=1024)


def report(**changes):
    result = dict(version=1, phase='run', exitCode=0, failureReason=None,
                  cpuUsec=100, wallNs=1000, peakMemoryBytes=4096,
                  oomKills=0, outputBytes=0, treeReaped=True)
    result.update(changes)
    return result


def decode(record):
    return decode_report(json.dumps(record), 'run', LIMITS)


def report_v2(**changes):
    result = dict(version=2, phase='run', exitCode=0, failureReason=None,
                  cpuUsec=100, wallNs=1000, peakMemoryBytes=4096,
                  oomKills=0, pidLimitHits=0, outputBytes=0, treeReaped=True)
    result.update(changes)
    return result


def test_clean_and_proven_resource_outcomes_are_accepted():
    for record in (
        report(),
        report(failureReason='memory_limit_exceeded', oomKills=1),
        report(failureReason='time_limit_exceeded', cpuUsec=1_000_000),
        report(failureReason='time_limit_exceeded', wallNs=2_000_000_000),
        report(failureReason='output_limit_exceeded', outputBytes=1024),
    ):
        assert decode(record) == record


@pytest.mark.parametrize('changes', [
    dict(failureReason='memory_limit_exceeded'),
    dict(oomKills=1),
    dict(failureReason='time_limit_exceeded', oomKills=1),
    dict(cpuUsec=1_000_000),
    dict(wallNs=2_000_000_000),
    dict(peakMemoryBytes=0),
    dict(outputBytes=1025),
    dict(treeReaped=False),
    dict(cpuUsec=True),
    dict(version=True),
])
def test_missing_or_contradictory_protected_evidence_is_rejected(changes):
    with pytest.raises(ValueError):
        decode(report(**changes))


def test_duplicate_field_and_oversized_record_are_rejected():
    with pytest.raises(ValueError, match='Duplicate supervisor field'):
        decode_report('{"version":1,"version":1}', 'run', LIMITS)
    with pytest.raises(ValueError, match='Oversized supervisor record'):
        decode_report(' ' * 4097, 'run', LIMITS)


def test_v2_pid_limit_evidence_is_required_and_oom_keeps_precedence():
    decoder=verified_contract('supervisor-record-v2').decode
    proven=report_v2(failureReason='process_limit_exceeded',pidLimitHits=1)
    assert decoder(json.dumps(proven),'run',LIMITS)==proven
    oom=report_v2(failureReason='memory_limit_exceeded',oomKills=1,pidLimitHits=1)
    assert decoder(json.dumps(oom),'run',LIMITS)==oom
    for invalid in (
        report_v2(failureReason='process_limit_exceeded'),
        report_v2(pidLimitHits=1),
        report_v2(failureReason='time_limit_exceeded',pidLimitHits=1,cpuUsec=1_000_000),
        report_v2(pidLimitHits=True),
    ):
        with pytest.raises(ValueError): decoder(json.dumps(invalid),'run',LIMITS)


def test_current_dispatcher_keeps_v1_and_v2_strictly_separate():
    assert decode(report())==report()
    assert decode(report_v2())==report_v2()
    mixed=report_v2();mixed['version']=1
    with pytest.raises(ValueError): decode(mixed)
