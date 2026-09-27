from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.models.judge_policy import JudgePolicy, StageLimits, SUPPORTED_LANGUAGES
from app.services.judge_runtime_registry import TOOLCHAINS,launcher_digest
from app.services.judge_policy import (
    COMPATIBILITY, candidate_limit, compatibility_public_limits, compatibility_receipt,
    content_hash, freeze_submission, public_limits, stored_policy,
    resource_fingerprint, test_suite_hash as suite_hash, validate_publishable,
)
from app.core.config import settings

SAMPLE = [{'input': '1\n', 'expected_output': '2\n'}]
HIDDEN = [{'input': 'SECRET_INPUT', 'expected_output': 'SECRET_EXPECTED'}]
LIMITS = dict(max_job_ms=120_000, max_reservation_bytes=2 * 1024**3)


def policy_fixture(sample=None, hidden=None, languages=('python',)):
    stage = dict(cpuMs=1000, wallMs=2000, memoryBytes=128 * 1024**2,
                 outputBytes=1024, pids=16, tmpBytes=16 * 1024**2)
    raw = dict(policyId='fixture', revision=1, reviewStatus='draft',
               testSuiteHash=suite_hash(SAMPLE if sample is None else sample, HIDDEN if hidden is None else hidden), preparationCleanupMs=1000,
               profiles={'python': dict(runtimeId='cpython313', runtimeVersion='3.13-test',
                   imageDigest='sha256:' + '1' * 64, workerClass='test-cpu', toolchainProfile='python-default',
                   launcherDigest='sha256:'+'4'*64,
                   compile=deepcopy(stage), run=deepcopy(stage))})
    raw['profiles'] = {language: deepcopy(raw['profiles']['python']) for language in languages}
    for language,profile in raw['profiles'].items():
        profile.update(toolchainProfile=TOOLCHAINS[language],launcherDigest=launcher_digest())
    parsed = JudgePolicy.model_validate(raw)
    count = len(SAMPLE if sample is None else sample) + len(HIDDEN if hidden is None else hidden)
    raw['evidence'] = {language: dict(reportHash='sha256:' + '2' * 64,
        resourceFingerprint=resource_fingerprint(parsed, language), hostClass='test-cpu',
        repetitions=10, caseCount=count, maxCpuMs=500, maxWallMs=1000,
        peakMemoryBytes=32 * 1024**2, safetyMarginReason='Synthetic unit fixture, not real measurements') for language in languages}
    raw['reviewStatus'] = 'verified'
    return raw


def install_synthetic_registry(tmp_path,monkeypatch):
    """Exact fixture identities only; not approval of real runtime images."""
    import json
    from app.core.config import settings
    policy=policy_fixture(languages=SUPPORTED_LANGUAGES)
    entries=[{'language':language,**{k:profile[k] for k in ('runtimeId','runtimeVersion','imageDigest',
        'workerClass','toolchainProfile','launcherDigest')}} for language,profile in policy['profiles'].items()]
    path=tmp_path/'synthetic-runtime-registry.json'
    path.write_text(json.dumps(dict(version=1,runtimes=entries)),encoding='utf-8')
    monkeypatch.setattr(settings,'JUDGE_RUNTIME_REGISTRY',str(path))
    return path


def test_existing_problem_compatibility_limits_are_explicit_and_language_specific():
    limits = compatibility_public_limits(2, settings=settings)
    languages = limits['languages']

    assert set(languages) == SUPPORTED_LANGUAGES
    assert limits['reviewStatus'] == 'compatibility'
    assert languages['cpp']['run']['wallMs'] == 2_000
    assert languages['python']['run']['wallMs'] == 4_000
    assert languages['java']['compile']['wallMs'] == 15_000
    assert languages['cpp']['run']['memoryBytes'] == 256 * 1024**2
    assert languages['javascript']['run']['memoryBytes'] == 384 * 1024**2
    with pytest.raises((ValidationError, ValueError)):
        stored_policy(COMPATIBILITY, creating=True)


def test_compatibility_receipt_binds_current_registry_without_inventing_measurement(tmp_path, monkeypatch):
    install_synthetic_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, 'JUDGE_WORKER_CLASS', 'test-cpu')

    receipts = {
        language: compatibility_receipt(language, SAMPLE, HIDDEN, settings=settings)
        for language in SUPPORTED_LANGUAGES
    }
    assert all(receipt['kind'] == 'measured-v1' for receipt in receipts.values())
    assert all(receipt['policyId'] == 'legacy-compatibility-v1' for receipt in receipts.values())
    assert all('evidence' not in receipt for receipt in receipts.values())
    assert all(receipt['jobDeadlineMs'] <= settings.EXECUTION_JOB_TIMEOUT_SECONDS * 1000
               for receipt in receipts.values())
    assert receipts['python']['profile']['run']['memoryBytes'] > receipts['cpp']['profile']['run']['memoryBytes']


@pytest.mark.parametrize(('base', 'factor', 'extra', 'floor', 'expected'), [
    (2000, '5', 0, 0, 10000), (2000, '1.5', 0, 0, 3000),
    (2000, '3', 2000, 0, 8000), (1, '1.5', 0, 0, 2),
    (100, '1', 0, 1000, 1000),
    (256 * 1024**2, '2', 32 * 1024**2, 0, 544 * 1024**2),
])
def test_candidate_affine_rounding_and_independent_memory(base, factor, extra, floor, expected):
    assert candidate_limit(base, factor, extra, floor) == expected


@pytest.mark.parametrize('factor', ['NaN', 'Infinity', '-1', '0', '101', '1e999999', 'oops', True, 1.5])
def test_invalid_candidate_factor(factor):
    with pytest.raises(ValueError):
        candidate_limit(1000, factor)


@pytest.mark.parametrize('value', [True, 1.5, -1, '1000'])
def test_candidate_rejects_coercion(value):
    with pytest.raises(ValueError):
        candidate_limit(value, '1')


@pytest.mark.parametrize(('field', 'value'), [
    ('cpuMs', True), ('cpuMs', 1.5), ('cpuMs', '1000'), ('cpuMs', 0),
    ('memoryBytes', -1), ('wallMs', 600001), ('pids', 257), ('outputBytes', 0),
    ('tmpBytes', 129 * 1024**2), ('unexpected', 5),
])
def test_stage_strict_numbers_and_bounds(field, value):
    limits = policy_fixture()['profiles']['python']['run']
    limits[field] = value
    with pytest.raises(ValidationError):
        StageLimits.model_validate(limits)


def test_verified_requires_all_measurements_and_headroom():
    policy = policy_fixture()
    for evidence in ({}, {'python': {**policy['evidence']['python'], 'repetitions': 9}},
                     {'python': {**policy['evidence']['python'], 'hostClass': 'other'}},
                     {'python': {**policy['evidence']['python'], 'maxCpuMs': 1000}}):
        with pytest.raises(ValidationError):
            JudgePolicy.model_validate({**policy, 'evidence': evidence})


@pytest.mark.parametrize('version', [True, '1', 1.0, 2])
def test_schema_version_cannot_be_coerced(version):
    with pytest.raises(ValidationError):
        JudgePolicy.model_validate({**policy_fixture(), 'schemaVersion': version})


def test_hash_canonicalization_preserves_whitespace_case_order_and_visibility():
    assert suite_hash(SAMPLE, HIDDEN) == suite_hash([{'input': '1\n', 'expectedOutput': '2\n'}], HIDDEN)
    assert suite_hash(SAMPLE, HIDDEN) != suite_hash(HIDDEN, SAMPLE)
    assert suite_hash(SAMPLE, HIDDEN) != suite_hash([{'input': '1', 'expectedOutput': '2\n'}], HIDDEN)
    assert content_hash({'a': 1, 'b': 2}) == content_hash({'b': 2, 'a': 1})


def test_policy_freezes_absolute_values_without_sharing_mutable_references():
    policy = policy_fixture()
    frozen = freeze_submission(policy, 'python', SAMPLE, HIDDEN, **LIMITS)
    assert frozen['jobDeadlineMs'] == 7000
    assert frozen['reservationBytes'] == 128 * 1024**2
    assert frozen['profile']['run']['cpuMs'] == 1000
    policy['profiles']['python']['run']['cpuMs'] = 99999
    assert frozen['profile']['run']['cpuMs'] == 1000
    assert 'evidence' not in frozen and 'SECRET' not in str(frozen)


def test_unpinned_supervisor_may_be_drafted_but_not_published():
    raw=policy_fixture();raw['profiles']['python'].pop('launcherDigest')
    raw['reviewStatus']='draft';raw['evidence']={}
    assert JudgePolicy.model_validate(raw).profiles['python'].launcher_digest is None
    raw['reviewStatus']='verified'
    raw['evidence']=policy_fixture()['evidence']
    with pytest.raises(ValueError,match='supervisor hash'):
        validate_publishable(raw,SAMPLE,HIDDEN,**LIMITS)


def test_supervisor_change_invalidates_old_measurement_evidence():
    raw=policy_fixture();raw['profiles']['python']['launcherDigest']='sha256:'+'5'*64
    with pytest.raises(ValueError,match='evidence'):
        validate_publishable(raw,SAMPLE,HIDDEN,**LIMITS)


@pytest.mark.parametrize('field', ['runtimeVersion', 'imageDigest', 'workerClass', 'toolchainProfile', 'run', 'compile'])
def test_changed_runtime_or_limits_invalidates_old_evidence(field):
    policy = policy_fixture()
    profile = policy['profiles']['python']
    if field == 'imageDigest':
        profile[field] = 'sha256:' + '3' * 64
    elif field in ('compile', 'run'):
        profile[field]['cpuMs'] += 1
    else:
        profile[field] = 'changed'
    with pytest.raises(ValueError):
        validate_publishable(policy, SAMPLE, HIDDEN, **LIMITS)


def test_publish_rejects_changed_cases_draft_missing_language_and_resource_cap():
    policy = policy_fixture()
    with pytest.raises(ValueError, match='Test suite changed'):
        validate_publishable(policy, SAMPLE, [{'input': 'different'}], **LIMITS)
    with pytest.raises(ValueError, match='Unmeasured'):
        validate_publishable({**policy, 'reviewStatus': 'draft'}, SAMPLE, HIDDEN, **LIMITS)
    with pytest.raises(ValueError, match='six language'):
        validate_publishable(policy, SAMPLE, HIDDEN, require_all_languages=True, **LIMITS)
    with pytest.raises(ValueError, match='not supported'):
        freeze_submission(policy, 'java', SAMPLE, HIDDEN, **LIMITS)
    with pytest.raises(ValueError, match='deadline'):
        validate_publishable(policy, SAMPLE, HIDDEN, **{**LIMITS, 'max_job_ms': 6999})
    with pytest.raises(ValueError, match='reservation'):
        validate_publishable(policy, SAMPLE, HIDDEN, **{**LIMITS, 'max_reservation_bytes': 1})


def test_all_languages_and_exact_boundaries_pass_without_double_counting_tmpfs():
    policy = policy_fixture()
    template = policy['profiles']['python']
    policy['profiles'] = {language: deepcopy(template) for language in SUPPORTED_LANGUAGES}
    policy['reviewStatus'] = 'draft'
    policy['evidence'] = {}
    parsed = JudgePolicy.model_validate(policy)
    policy['evidence'] = {language: {**policy_fixture()['evidence']['python'],
        'resourceFingerprint': resource_fingerprint(parsed, language)} for language in SUPPORTED_LANGUAGES}
    policy['reviewStatus'] = 'verified'
    validate_publishable(policy, SAMPLE, HIDDEN, max_job_ms=7000,
                         max_reservation_bytes=128 * 1024**2, require_all_languages=True)
    public = public_limits(policy)
    assert len(public['languages']) == 6
    assert 'evidence' not in public and 'testSuiteHash' not in public
