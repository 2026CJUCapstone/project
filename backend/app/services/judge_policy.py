"""Pure validation/freezing helpers for server-owned judge policies."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json

from app.models.judge_policy import JudgePolicy, RuntimeLimits, StageLimits, SUPPORTED_LANGUAGES
from app.models.judge_test_manifest import canonical_suite,has_stored_cases,test_data_buffer_bytes


UNREVIEWED = {'kind': 'unreviewed-v1'}
COMPATIBILITY = {'kind': 'compatibility-v1'}

# Existing inline-test problems predate measured authoring. These limits are
# explicit operator defaults, not fabricated benchmark evidence. New or edited
# content must still pass the measured publication gate.
_COMPAT_TIME_MS = {
    'bpp': (30_000, 2_000), 'c': (10_000, 2_000), 'cpp': (10_000, 2_000),
    'python': (5_000, 4_000), 'java': (15_000, 4_000), 'javascript': (5_000, 4_000),
}
_COMPAT_MEMORY_BYTES = {
    'bpp': 256 * 1024**2, 'c': 256 * 1024**2, 'cpp': 256 * 1024**2,
    'python': 384 * 1024**2, 'java': 384 * 1024**2, 'javascript': 384 * 1024**2,
}


def _compat_stage_limits(language, case_count, settings):
    compile_ms, preferred_run_ms = _COMPAT_TIME_MS[language]
    cleanup_ms = 5_000
    ceiling_ms = int(settings.EXECUTION_JOB_TIMEOUT_SECONDS * 1000)
    remaining = ceiling_ms - compile_ms - cleanup_ms
    if case_count < 1 or remaining < case_count:
        raise ValueError('Compatibility problem cannot fit the execution deadline')
    run_ms = min(preferred_run_ms, remaining // case_count)
    memory = _COMPAT_MEMORY_BYTES[language]
    compile_limits = StageLimits(cpu_ms=compile_ms, wall_ms=compile_ms,
        memory_bytes=memory, output_bytes=1024**2, pids=64, tmp_bytes=64 * 1024**2)
    run_limits = StageLimits(cpu_ms=run_ms, wall_ms=run_ms,
        memory_bytes=memory, output_bytes=1024**2, pids=64, tmp_bytes=16 * 1024**2)
    return compile_limits, run_limits, cleanup_ms


def compatibility_public_limits(case_count, *, settings):
    languages = {}
    for language in sorted(SUPPORTED_LANGUAGES):
        compile_limits, run_limits, _ = _compat_stage_limits(language, case_count, settings)
        languages[language] = {
            'runtimeVersion': '운영 기본 환경',
            'compile': compile_limits.model_dump(by_alias=True),
            'run': run_limits.model_dump(by_alias=True),
        }
    return {'policyId': 'legacy-compatibility-v1', 'revision': 1,
            'reviewStatus': 'compatibility', 'languages': languages}


def compatibility_receipt(language, sample, hidden, *, settings):
    from app.services.judge_runtime_registry import RuntimeRegistry
    case_count = len(sample) + len(hidden)
    compile_limits, run_limits, cleanup_ms = _compat_stage_limits(language, case_count, settings)
    registry = RuntimeRegistry.load(settings.JUDGE_RUNTIME_REGISTRY)
    registration = registry.admission_registration(language, settings.JUDGE_WORKER_CLASS)
    profile = RuntimeLimits(
        runtime_id=registration.runtime_id, runtime_version=registration.runtime_version,
        image_digest=registration.image_digest, worker_class=registration.worker_class,
        toolchain_profile=registration.toolchain_profile, launcher_digest=registration.launcher_digest,
        compile=compile_limits, run=run_limits,
    )
    buffers = test_data_buffer_bytes(sample, hidden)
    reservation = max(compile_limits.memory_bytes, run_limits.memory_bytes) + buffers
    if reservation > policy_memory_budget(settings):
        raise ValueError('Compatibility problem exceeds the worker memory budget')
    identity = {'kind': 'compatibility-v1', 'language': language,
                'testSuiteHash': test_suite_hash(sample, hidden),
                'profile': profile.model_dump(by_alias=True)}
    return {
        'kind': 'measured-v1', 'policyId': 'legacy-compatibility-v1', 'revision': 1,
        'policyHash': content_hash(identity), 'language': language,
        'testSuiteHash': identity['testSuiteHash'], 'profile': identity['profile'],
        'jobDeadlineMs': compile_limits.wall_ms + case_count * run_limits.wall_ms + cleanup_ms,
        'reservationBytes': reservation,
        **({'testDataBufferBytes': buffers} if buffers else {}),
    }


def stored_policy(policy, *, previous=None, creating=False) -> dict | None:
    """Never turn a new/missing author policy into the legacy escape hatch.

    Omitting a field on an existing problem retains its policy, including its
    test fingerprint. Changing tests therefore invalidates measured evidence.
    Only additive migration/internal legacy seeds may introduce NULL.
    """
    if policy is not None:
        canonical = JudgePolicy.model_validate(policy).model_dump(by_alias=True)
        if previous is not None and previous not in (UNREVIEWED, COMPATIBILITY):
            old = JudgePolicy.model_validate(previous)
            if canonical != old.model_dump(by_alias=True):
                if canonical['policyId'] != old.policy_id or canonical['revision'] <= old.revision:
                    raise ValueError('제한 정책을 변경할 때는 같은 정책 ID의 새 버전을 사용하세요.')
        return canonical
    return deepcopy(UNREVIEWED if creating else previous)


def public_policy_fields(policy) -> dict:
    if policy == COMPATIBILITY:
        return {'judgeLimits': None, 'judgePolicyLegacy': False, 'judgePolicyCompatibility': True}
    return {'judgeLimits': None if policy is None or policy == UNREVIEWED else public_limits(policy),
            'judgePolicyLegacy': policy is None, 'judgePolicyCompatibility': False}


def public_policy_fields_for_problem(policy, case_count, *, settings):
    if policy == COMPATIBILITY:
        return {'judgeLimits': compatibility_public_limits(case_count, settings=settings),
                'judgePolicyLegacy': False, 'judgePolicyCompatibility': True}
    return public_policy_fields(policy)


def validate_stored_publication(policy, sample, hidden, *, settings):
    if policy == COMPATIBILITY:
        return
    if policy is None:
        if has_stored_cases(sample,hidden):
            raise ValueError('Stored test data requires a measured judge policy')
        return  # Existing legacy problem: no invented measurements.
    if policy == UNREVIEWED:
        raise ValueError('측정·검수된 언어별 채점 제한이 있어야 문제를 공개할 수 있습니다.')
    parsed = validate_publishable(policy, sample, hidden,
        max_job_ms=int(settings.EXECUTION_JOB_TIMEOUT_SECONDS * 1000),
        max_reservation_bytes=policy_memory_budget(settings))
    from app.services.judge_runtime_registry import require_registered_policy
    require_registered_policy(parsed,settings)
    return parsed


def policy_memory_budget(settings):
    """Measured limits use the host allowance, not the old per-container cap."""
    available = (settings.EXECUTION_MEMORY_BUDGET_MB - settings.EXECUTION_JOB_OVERHEAD_MB) * 1024**2
    if available <= 0 or settings.EXECUTION_CPU_BUDGET_MILLIS < 1000:
        raise ValueError('Worker host budget cannot fit a measured execution lane')
    return available


def freeze_stored_submission(policy, language, sample, hidden, *, settings) -> dict:
    """Receipt-owned contract, distinct from mutable source problem settings."""
    validate_stored_publication(policy, sample, hidden, settings=settings)
    if policy == COMPATIBILITY:
        return compatibility_receipt(language, sample, hidden, settings=settings)
    if policy is not None:
        return freeze_submission(policy, language, sample, hidden,
            max_job_ms=int(settings.EXECUTION_JOB_TIMEOUT_SECONDS * 1000),
            max_reservation_bytes=policy_memory_budget(settings))
    # Honest compatibility receipt. CPU/peak/RSS were not measured in legacy
    # judging; do not manufacture modern per-stage CPU or memory guarantees.
    return {'kind': 'legacy-v1', 'language': language,
            'testSuiteHash': test_suite_hash(sample, hidden),
            'wallMs': settings.EXECUTION_TIMEOUT * 1000,
            'memoryBytes': settings.SANDBOX_MEMORY_MB * 1024**2,
            'outputBytes': settings.SANDBOX_OUTPUT_MAX_BYTES,
            'pids': settings.SANDBOX_PIDS_LIMIT,
            'cpuQuota': settings.SANDBOX_CPU_LIMIT,
            'runtimeImage': settings.SANDBOX_IMAGE,
            'openFiles': settings.SANDBOX_NOFILE_LIMIT,
            'jobDeadlineMs': int(settings.EXECUTION_JOB_TIMEOUT_SECONDS * 1000)}


def content_hash(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def test_suite_hash(sample, hidden) -> str:
    return content_hash(canonical_suite(sample, hidden))


def resource_fingerprint(policy: JudgePolicy, language: str) -> str:
    return content_hash({'language': language, 'testSuiteHash': policy.test_suite_hash,
                         'profile': policy.profiles[language].model_dump(by_alias=True),
                         'preparationCleanupMs': policy.preparation_cleanup_ms})


def candidate_limit(base: int, factor: str, extra: int = 0, floor: int = 0) -> int:
    """Authoring-only affine candidate, rounding up without silent service caps.

    Caller supplies one unit throughout (milliseconds OR bytes); time and memory
    calculations must be independent. A candidate is not measured/verified.
    """
    if any(type(value) is not int or value < 0 for value in (base, extra, floor)):
        raise ValueError('Base, additional allowance and floor must be nonnegative integers')
    if not isinstance(factor, str) or len(factor) > 40:
        raise ValueError('Factor must be a bounded decimal string')
    try:
        multiplier = Decimal(factor)
    except InvalidOperation as exc:
        raise ValueError('Invalid decimal factor') from exc
    if not multiplier.is_finite() or not Decimal('0') < multiplier <= Decimal('100'):
        raise ValueError('Factor must be finite and in (0, 100]')
    return max(int((Decimal(base) * multiplier + extra).to_integral_value(rounding=ROUND_CEILING)), floor)


def validate_publishable(policy, sample, hidden, *, max_job_ms: int,
                         max_reservation_bytes: int, require_all_languages=False) -> JudgePolicy:
    parsed = JudgePolicy.model_validate(policy)
    if parsed.review_status != 'verified':
        raise ValueError('Unmeasured judge policy cannot be published')
    count = len(sample) + len(hidden)
    buffer_bytes=test_data_buffer_bytes(sample,hidden)
    if not 1 <= count <= 200:
        raise ValueError('A judged package must contain 1 to 200 cases')
    if parsed.test_suite_hash != test_suite_hash(sample, hidden):
        raise ValueError('Test suite changed after resource validation')
    if require_all_languages and set(parsed.profiles) != SUPPORTED_LANGUAGES:
        raise ValueError('This contest requires all six language profiles')
    for language, profile in parsed.profiles.items():
        if profile.launcher_digest is None:
            raise ValueError('Exact measured supervisor hash is required before publication')
        if min(profile.compile.pids,profile.run.pids)<2 or profile.compile.tmp_bytes==0:
            raise ValueError('Measured phases need supervisor/child PIDs and compilation artifact space')
        evidence = parsed.evidence[language]
        if evidence.case_count != count or evidence.resource_fingerprint != resource_fingerprint(parsed, language):
            raise ValueError('Measurement evidence does not match the exact test/runtime/limits')
        budget = profile.compile.wall_ms + count * profile.run.wall_ms + parsed.preparation_cleanup_ms
        if budget > max_job_ms:
            raise ValueError('Whole-submission deadline exceeds the service budget')
        if max(profile.compile.memory_bytes, profile.run.memory_bytes)+buffer_bytes > max_reservation_bytes:
            raise ValueError('Job memory reservation exceeds the worker budget')
    return parsed


def freeze_submission(policy, language, sample, hidden, *, max_job_ms: int,
                      max_reservation_bytes: int) -> dict:
    parsed = validate_publishable(policy, sample, hidden, max_job_ms=max_job_ms,
                                  max_reservation_bytes=max_reservation_bytes)
    if language not in parsed.profiles:
        raise ValueError('Language is not supported by the frozen problem policy')
    selected = parsed.profiles[language]
    canonical = parsed.model_dump(by_alias=True)
    buffer_bytes=test_data_buffer_bytes(sample,hidden)
    return deepcopy({
        'kind': 'measured-v1', 'policyId': parsed.policy_id, 'revision': parsed.revision,
        'policyHash': content_hash(canonical), 'language': language,
        'testSuiteHash': parsed.test_suite_hash,
        'profile': selected.model_dump(by_alias=True),
        'jobDeadlineMs': selected.compile.wall_ms + (len(sample) + len(hidden)) * selected.run.wall_ms
                         + parsed.preparation_cleanup_ms,
        # Compile and execution are serial; tmpfs is already inside cgroup memory.
        'reservationBytes': max(selected.compile.memory_bytes, selected.run.memory_bytes)+buffer_bytes,
        **({'testDataBufferBytes':buffer_bytes} if buffer_bytes else {}),
    })


def public_limits(policy) -> dict:
    parsed = JudgePolicy.model_validate(policy)
    return {'policyId': parsed.policy_id, 'revision': parsed.revision,
            'reviewStatus': parsed.review_status,
            'languages': {language: {'runtimeVersion': profile.runtime_version,
                                     'compile': profile.compile.model_dump(by_alias=True),
                                     'run': profile.run.model_dump(by_alias=True)}
                          for language, profile in parsed.profiles.items()}}
