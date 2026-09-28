"""Measure fixed correct-but-slow Python F/I/J programs against their fast peers.

This is a one-case-per-submission diagnostic on the unapproved v2 draft corpus.
It never approves a contest limit or writes to the operating database/queue.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

from verify_freshman_measurements import draft_cases_for, reference_path, sha, validate_reference_result
from verify_runtime_matrix import (cleanup_phase_containers,preserve_primary_cleanup_error,
                                   require_disposable_workspace,verify_child_options)


TARGETS = {
    'F': 'f-linear-scan-discriminator-mostly-absent-queries',
    'I': 'i-maximum-many-sources-front-delete-discriminator',
    'J': 'j-maximum-unit-total-long-positive-negative-blocks-int64',
}
SLOW_SOURCE_SHA256 = {
    'F': '33415aea19d1193568a1bfd396b829fa1bedda12c2c0e3622e2f013eceb1474a',
    'I': 'cfbf02504680fe763bc482860a5cf5e4f633b2806e4e61dd5ff1c9d17dc2c282',
    'J': '19f3b78dfd026f7c62251751ed567367323dee2c27203f6df45e86a262dbbd99',
}
CPU_MS = 5000
WALL_MS = 8000


def slow_source_path(base, letter):
    if letter not in TARGETS:
        raise ValueError('Only fixed F/I/J slow sources may be measured')
    path = base / 'slow_solutions' / 'python' / f'{letter}.py'
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('Missing, linked or oversized slow source')
    if hashlib.sha256(path.read_bytes()).hexdigest() != SLOW_SOURCE_SHA256[letter]:
        raise ValueError('Slow source identity changed')
    return path


def target_case(base, letter):
    sample, hidden, identities, manifest_hash = draft_cases_for(letter, base)
    index = next((n for n, identity in enumerate(identities)
                  if identity['name'] == TARGETS[letter]), None)
    if index is None or index < len(sample) or identities[index]['visibility'] != 'hidden':
        raise ValueError('Fixed slow discriminator is missing or public')
    case = hidden[index - len(sample)]
    identity = identities[index]
    if (sha(case['input'].encode()) != identity['inputHash'] or
            sha(case['expected_output'].encode()) != identity['expectedHash']):
        raise ValueError('Slow discriminator bytes changed')
    return case, identity, manifest_hash


def validate_pair(fast, slow, payload, fast_phase_names, slow_phase_names):
    """Accept TLE separation only with a bound CPU/wall witness, not a label alone."""
    from app.services.judge_metrics import validate_report
    fast_phases = validate_reference_result(fast, payload, fast_phase_names)
    fast_run = fast_phases[-1]
    report = slow.get('_resource_report')
    validate_report(report, payload)
    slow_phases = [report['compile']] + [case['usage'] for case in report['cases']]
    if (len(slow_phases) != 2 or len(slow_phase_names) != 2 or
            len(set(slow_phase_names)) != 2 or
            any(p['treeReaped'] is not True for p in slow_phases) or
            slow_phases[0]['exitCode'] != 0 or slow_phases[0]['failureReason'] is not None or
            len(report['cases']) != 1 or report['cases'][0]['verdict'] != slow.get('verdict')):
        raise ValueError('Slow result has an invalid compile/run phase sequence')
    verdict = slow['verdict']
    if verdict in ('system_error', 'compile_error'):
        raise ValueError('Slow result is infrastructure or compilation failure')
    run = slow_phases[-1]
    limits = payload['judge_contract']['profile']['run']
    cpu_hit = run['cpuUsec'] >= limits['cpuMs'] * 1000
    wall_hit = run['wallNs'] >= limits['wallMs'] * 1000000
    if verdict == 'time_limit_exceeded':
        if run['failureReason'] != 'time_limit_exceeded' or not (cpu_hit or wall_hit) or run['oomKills']:
            raise ValueError('Slow time-limit verdict has no CPU/wall witness')
    elif verdict == 'accepted':
        if run['exitCode'] != 0 or run['failureReason'] is not None or run['oomKills']:
            raise ValueError('Slow accepted result did not finish cleanly')
    return dict(fastVerdict='accepted', slowVerdict=verdict,
                separates=verdict == 'time_limit_exceeded',
                limitAxis=('cpu+wall' if cpu_hit and wall_hit else 'cpu' if cpu_hit else 'wall' if wall_hit else None)
                if verdict == 'time_limit_exceeded' else None,
                fastRun=fast_run, slowRun=run)


async def verify(args):
    if os.environ.get('DATABASE_URL') != 'sqlite:///:memory:':
        raise RuntimeError('In-memory isolated DB configuration required')
    root = require_disposable_workspace(args.workspace)
    from app.core.config import settings
    from app.services.compiler import DockerCompilerRunner
    from app.services.judge_policy import content_hash, test_suite_hash
    from app.services.judge_runtime_registry import TOOLCHAINS, launcher_digest, RuntimeRegistry
    from app.services.measured_judge import MeasuredSubmission
    from app.services.judging import judge_code

    base = Path('/candidate/tools/freshman_contest')
    versions = json.loads(Path('/versions.json').read_text())
    settings.SANDBOX_WORKDIR_ROOT = str(root / 'jobs')
    settings.JUDGE_WORKER_CLASS = 'isolated-freshman-slow-comparison'
    registry = root / 'reference-registry.json'
    entry = dict(language='python', runtimeId='isolated-python',
                 runtimeVersion=versions['python']['version'], imageDigest=args.image,
                 workerClass=settings.JUDGE_WORKER_CLASS, toolchainProfile=TOOLCHAINS['python'],
                 launcherDigest=launcher_digest())
    with registry.open('x', encoding='utf-8') as stream:
        json.dump(dict(version=1, runtimes=[entry]), stream)
    settings.JUDGE_RUNTIME_REGISTRY = str(registry)
    names = []

    class Runner(DockerCompilerRunner):
        async def _allocate_container(self, create, **options):
            if len(names) >= 12:
                raise RuntimeError('Slow comparison container ceiling')
            verify_child_options(options, root, args.image, args.owner)
            names.append(options['name'])
            return await super()._allocate_container(create, **options)

        def measured_submission(self, payload):
            return MeasuredSubmission(self, payload, RuntimeRegistry.load(settings.JUDGE_RUNTIME_REGISTRY),
                                      settings.JUDGE_WORKER_CLASS)

    runner = Runner(labels={'webcompiler.isolated-runtime-matrix': args.owner})
    client = runner._get_client()
    rows = []
    try:
        for letter in TARGETS:
            case, identity, manifest_hash = target_case(base, letter)
            fast_source = reference_path(base, 'python', letter).read_bytes()
            slow_source = slow_source_path(base, letter).read_bytes()
            compile_limits = dict(cpuMs=8000, wallMs=10000, memoryBytes=512*1024**2,
                                  outputBytes=512*1024, pids=64, tmpBytes=64*1024**2)
            run_limits = dict(cpuMs=CPU_MS, wallMs=WALL_MS, memoryBytes=512*1024**2,
                              outputBytes=512*1024, pids=64, tmpBytes=16*1024**2)
            profile = {k:v for k,v in entry.items() if k != 'language'}
            profile.update(compile=compile_limits, run=run_limits)
            contract = dict(kind='measured-v1', policyId='isolated-slow-'+letter, revision=1,
                            policyHash=content_hash(profile), language='python',
                            testSuiteHash=test_suite_hash([], [case]), profile=profile,
                            jobDeadlineMs=compile_limits['wallMs']+run_limits['wallMs']+5000,
                            reservationBytes=512*1024**2)
            payload = dict(language='python', code='', sample=[], hidden=[case], judge_contract=contract)
            row = dict(letter=letter, case=identity, corpusManifestHash=manifest_hash,
                       fastSourceHash=sha(fast_source), slowSourceHash=sha(slow_source),
                       contract=contract, startedAt=datetime.now(timezone.utc).isoformat())
            payload['code'] = fast_source.decode('utf-8')
            start = len(names)
            fast = await asyncio.wait_for(judge_code(runner, payload), timeout=contract['jobDeadlineMs']/1000)
            fast_names = names[start:]
            payload['code'] = slow_source.decode('utf-8')
            start = len(names)
            slow = await asyncio.wait_for(judge_code(runner, payload), timeout=contract['jobDeadlineMs']/1000)
            row.update(validate_pair(fast, slow, payload, fast_names, names[start:]))
            remaining = client.containers.list(all=True, filters={'label':f'webcompiler.isolated-runtime-matrix={args.owner}'})
            if any(container.name in names for container in remaining) or list((root/'jobs').iterdir()):
                raise RuntimeError('Unconfirmed slow comparison cleanup; refusing next pair')
            row['finishedAt'] = datetime.now(timezone.utc).isoformat()
            rows.append(row)
            print(json.dumps(row), flush=True)
            del case, payload, fast, slow
        print(json.dumps(dict(scope='Fixed F/I/J slow-vs-fast draft diagnostics only; not final limits',
                              pairs=len(rows), separated=sum(row['separates'] for row in rows),
                              corpusManifestHash=rows[0]['corpusManifestHash'],
                              phaseContainers=len(names), remainingSubmittedContainers=0,
                              remainingJobDirectories=0)), flush=True)
    finally:
        primary=sys.exc_info()[1]
        errors=cleanup_phase_containers(client,names,args.owner)
        try:
            registry.unlink(missing_ok=True)
        except Exception as exc:
            errors.append('registry:'+type(exc).__name__)
        preserve_primary_cleanup_error(primary,errors,'freshman-slow')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--language', required=True, choices=['python'])
    parser.add_argument('--repetition', type=int, choices=range(1,11), default=1)
    parser.add_argument('--draft-corpus', action='store_true')
    args = parser.parse_args()
    if (not args.execute or not args.draft_corpus or sys.platform != 'linux' or
            not re.fullmatch(r'sha256:[a-f0-9]{64}', args.image) or
            not re.fullmatch(r'[a-f0-9]{32}', args.owner)):
        raise SystemExit('Explicit isolated Linux draft authorization and immutable identities required')
    asyncio.run(verify(args))
