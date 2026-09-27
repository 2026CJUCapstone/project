"""Explicit, sequential six-runtime smoke using only existing immutable images.

No production data mounts, database, queue, image build or installation.
The trusted controller has authority over one explicitly identified dedicated
Docker daemon.  The default host socket is rejected; ``--network=none`` alone
is not treated as a daemon security boundary.
Controller <=384MiB/0.5 CPU; one child <=512MiB/1 CPU; no swap. Not a benchmark.
"""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import time
import uuid
from types import SimpleNamespace

REFERENCE_ARCHIVE_SHA256='8dae6743dbf815bb58c310c0111f5c18bf3070508c8cda4fe485862800e633ab'
DRAFT_REFERENCE_ARCHIVE_SHA256='053472836c1e7fe5b2652cadb2697dc88046cb16dbba1c6af0ec4ce8b9d18ebc'
SLOW_REFERENCE_ARCHIVE_SHA256='a90de99a98085194e3d6cd371f76c74fa3727efc60c8f31c1f35aec9fcc596a0'
MEASURED_APP_SOURCE_ARCHIVE_SHA256='2e18d203661ac3932f11b965b7ceb0abde190a607a1d27a61bac0b8911e70a68'
CANDIDATE_SOURCE_ARCHIVE_SHA256='010e9abd3e2469b6bd1b4ee006ed142e695ecf8ee8af0b81b62fac764d2355bf'
CANDIDATE_STAGE2_GZIP_SHA256='84d06f51cc23eb6076edf3d50f9d43a2fca92f73f749c76b5b5e2e2211f2d846'
TRUSTED_CONTROLLER_FILES={
    'verify_runtime_matrix.py':'76604bc07feaf8c3007f8d2adc8de91331e40e63ed18fd887ee932696c4d60c7',
    'verify_freshman_measurements.py':'b2276320977a3bc4407f08f0128fcb7e4942f7682add09ccb34165f397a7b09a',
    'verify_freshman_slow.py':'3fbfc1c20227cf2fd3a70de364f665dbef3b83d5a1e8998f2b26d6aff9ffbef5',
    'bpp_candidate_overlay.py':'b8afb377023647dd809bc6b5b69cfab286d73b7934faf757fd88b0956747e74b',
    'probe_bpp_candidate.py':'87ef6e66a0a1f16ac15edc98288e9e873c1808349482c107b40b1e6b69c6789e',
}

# These are frozen-suite maxima, not contest limits.  The child receipts remain
# the authority for each job; this outer watchdog only prevents a healthy
# sequence from being killed before all of its individually bounded jobs can
# finish.  Keep the constants aligned with the hashed reference archives and
# their verifier tests.
CONTROLLER_OVERHEAD_SECONDS = 60
MECHANICS_CHECK_SECONDS = 30
REFERENCE_PROBLEM_COUNT = 10
REFERENCE_CASE_COUNT = 31
DRAFT_CASE_COUNT = 79
DIAGNOSTIC_PROGRAM_COUNT = 6
SLOW_TARGET_COUNT = 3
DEFAULT_DOCKER_SOCKET_PATHS = frozenset(('/var/run/docker.sock', '/run/docker.sock'))


def command(*args,timeout=10):
    value=subprocess.run(['docker',*args],capture_output=True,timeout=timeout)
    if value.returncode:
        raise RuntimeError('Docker isolated operation failed: '+args[0])
    return value.stdout


def capacity():
    fields={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()}
    free=shutil.disk_usage('/').free
    if fields['MemAvailable']<2*1024**3 or free<4*1024**3:
        raise RuntimeError('Isolated capacity floor not met')
    return dict(availableMemoryBytes=fields['MemAvailable'],freeDiskBytes=free)


def _portable_absolute_path(path: Path) -> str:
    """Normalize only for comparing reserved Unix socket names in offline tests."""
    return '/' + str(path).replace('\\', '/').lstrip('/')


def bind_dedicated_daemon(socket_path, expected_id_sha256, *, socket_checker=None,
                          docker_command=command):
    """Select and bind one non-default Unix Docker daemon before any operation.

    The daemon ID hash is operator-provided evidence that an explicit socket did
    not silently resolve to another engine.  This does not provision the daemon;
    it only makes the harness fail closed until one has been identified.
    """
    path = Path(socket_path)
    if os.name != 'posix' and socket_checker is None:
        raise RuntimeError('Dedicated Unix Docker socket requires a POSIX host')
    path_text = _portable_absolute_path(path)
    if (len(path_text.encode('utf-8')) > 240 or ',' in path_text
            or any(ord(char) < 33 or ord(char) == 127 for char in path_text)):
        raise ValueError('Dedicated Docker socket path is outside the reviewed syntax')
    if (_portable_absolute_path(path) in DEFAULT_DOCKER_SOCKET_PATHS
            or path.is_symlink()):
        raise RuntimeError('Default or symlinked Docker socket is not an isolated daemon')
    if not re.fullmatch(r'[a-f0-9]{64}', expected_id_sha256 or ''):
        raise ValueError('Exact dedicated daemon ID SHA-256 is required')
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise RuntimeError('Dedicated Docker socket does not exist') from None
    if _portable_absolute_path(resolved) in DEFAULT_DOCKER_SOCKET_PATHS:
        raise RuntimeError('Dedicated Docker socket resolves to the default daemon')
    checker = socket_checker or (lambda candidate: stat.S_ISSOCK(candidate.stat().st_mode))
    if not checker(resolved):
        raise RuntimeError('Dedicated Docker endpoint is not a Unix socket')

    previous_host = os.environ.get('DOCKER_HOST')
    os.environ['DOCKER_HOST'] = 'unix://' + resolved.as_posix()
    try:
        daemon_id = docker_command('info', '--format={{.ID}}', timeout=10).decode().strip()
        if (not daemon_id or len(daemon_id) > 256
                or any(ord(char) < 33 or ord(char) == 127 for char in daemon_id)):
            raise RuntimeError('Dedicated Docker daemon returned an invalid identity')
        actual = hashlib.sha256(daemon_id.encode('utf-8')).hexdigest()
        if actual != expected_id_sha256:
            raise RuntimeError('Dedicated Docker daemon identity mismatch')
    except BaseException:
        if previous_host is None:
            os.environ.pop('DOCKER_HOST', None)
        else:
            os.environ['DOCKER_HOST'] = previous_host
        raise
    return resolved, actual


def require_private_root(root, *, platform_name=None, effective_uid=None, stat_reader=None):
    """Require one owner-only, non-symlink disposable host directory."""
    platform_name = os.name if platform_name is None else platform_name
    if platform_name != 'posix' and stat_reader is None:
        raise RuntimeError('Disposable runtime root requires a POSIX host')
    path = Path(root)
    try:
        metadata = stat_reader(path) if stat_reader else path.lstat()
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise RuntimeError('Disposable runtime root does not exist') from None
    uid = os.geteuid() if effective_uid is None else effective_uid
    if (not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != uid or stat.S_IMODE(metadata.st_mode) & 0o077
            or resolved != path):
        raise RuntimeError('Disposable runtime root must be owner-only and canonical')
    return resolved


def _fixed_file(path, expected, maximum):
    try:
        metadata=path.lstat()
    except OSError:
        raise RuntimeError('Required fixed runtime input is missing') from None
    if (not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)
            or not 0 < metadata.st_size <= maximum):
        raise RuntimeError('Required fixed runtime input is not a bounded regular file')
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    if actual!=expected:
        raise RuntimeError('Required fixed runtime input identity mismatch')
    return actual


def reference_archive_sha256(suite):
    """Return the sole reviewed reference archive identity for one suite."""
    if suite == 'mechanics':
        return None
    if suite in ('freshman', 'freshman-candidate', 'bpp-diagnostic'):
        return REFERENCE_ARCHIVE_SHA256
    if suite in ('freshman-draft', 'freshman-draft-candidate'):
        return DRAFT_REFERENCE_ARCHIVE_SHA256
    if suite == 'freshman-slow':
        return SLOW_REFERENCE_ARCHIVE_SHA256
    raise ValueError('Unknown controller suite')


def verify_fixed_inputs(root, *, suite, harness_sha256, trusted_files=None,
                        source_sha256=MEASURED_APP_SOURCE_ARCHIVE_SHA256):
    """Pin every controller-executed byte before the first Docker operation."""
    if not re.fullmatch(r'[a-f0-9]{64}', harness_sha256 or ''):
        raise ValueError('Exact outer harness SHA-256 is required')
    trusted_files = TRUSTED_CONTROLLER_FILES if trusted_files is None else trusted_files
    identities={
        'run_isolated_runtime_matrix.py':_fixed_file(
            root/'run_isolated_runtime_matrix.py',harness_sha256,128*1024),
        'measured-app-source.tar.gz':_fixed_file(
            root/'measured-app-source.tar.gz',source_sha256,8*1024**2),
    }
    expected_archive=reference_archive_sha256(suite)
    slow=suite=='freshman-slow'
    candidate=suite in ('freshman-candidate','freshman-draft-candidate')
    probe_name=('verify_runtime_matrix.py' if suite=='mechanics' else
                'verify_freshman_slow.py' if slow else
                'verify_freshman_measurements.py')
    names={'verify_runtime_matrix.py',probe_name}
    if slow: names.add('verify_freshman_measurements.py')
    if candidate: names.update(('bpp_candidate_overlay.py','probe_bpp_candidate.py'))
    for name in names:
        expected=trusted_files.get(name)
        if not expected:
            raise RuntimeError('Controller script is not in the trusted manifest')
        identities[name]=_fixed_file(root/name,expected,512*1024)
    if expected_archive:
        identities['freshman-package.tar.gz']=_fixed_file(
            root/'freshman-package.tar.gz',expected_archive,4*1024**2)
    if candidate:
        identities['compiler.tar.gz']=_fixed_file(
            root/'compiler.tar.gz',CANDIDATE_SOURCE_ARCHIVE_SHA256,2*1024**2)
        identities['candidate-stage2.gz']=_fixed_file(
            root/'candidate-stage2.gz',CANDIDATE_STAGE2_GZIP_SHA256,8*1024**2)
    return identities


def controller_timeout_seconds(suite, language):
    if suite == 'mechanics':
        # Three checks per selected runtime, plus six Python resource checks
        # only in the full matrix.  Each inner check is capped at 30 seconds.
        checks = 24 if language == 'all' else 3
        timeout = checks * MECHANICS_CHECK_SECONDS + CONTROLLER_OVERHEAD_SECONDS
    elif suite in ('freshman', 'freshman-candidate'):
        # Per problem: 10s compile + N*10s case wall + 5s cleanup allowance.
        timeout = (REFERENCE_PROBLEM_COUNT * 15 + REFERENCE_CASE_COUNT * 10
                   + CONTROLLER_OVERHEAD_SECONDS)
    elif suite in ('freshman-draft', 'freshman-draft-candidate'):
        # Frozen v2 corpus: 79 total cases, 8s diagnostic wall cap per case.
        timeout = (REFERENCE_PROBLEM_COUNT * 15 + DRAFT_CASE_COUNT * 8
                   + CONTROLLER_OVERHEAD_SECONDS)
    elif suite == 'freshman-slow':
        # Three fixed targets, fast and slow submission each: 10+8+5 seconds.
        timeout = SLOW_TARGET_COUNT * 2 * 23 + CONTROLLER_OVERHEAD_SECONDS
    elif suite == 'bpp-diagnostic':
        # Six one-case reductions: 10s compile + 3s run + 5s cleanup each.
        timeout = DIAGNOSTIC_PROGRAM_COUNT * 18 + CONTROLLER_OVERHEAD_SECONDS
    else:
        raise ValueError('Unknown controller suite')
    if not 60 <= timeout <= 1200:
        raise ValueError('Controller timeout outside reviewed bound')
    return timeout


def controller_watchdog_evidence(suite, language, elapsed_seconds, timed_out):
    timeout = controller_timeout_seconds(suite, language)
    return dict(
        language=language,
        controllerTimeoutSeconds=timeout,
        controllerTimeoutBasis=dict(
            kind='frozen-suite-inner-deadlines-plus-reviewed-overhead',
            frozenInnerDeadlineSeconds=timeout-CONTROLLER_OVERHEAD_SECONDS,
            reviewedNonJobOverheadSeconds=CONTROLLER_OVERHEAD_SECONDS,
        ),
        controllerElapsedSeconds=round(max(0.0, elapsed_seconds), 3),
        timedOut=bool(timed_out),
    )


def cleanup_owned_containers(label, owner):
    """Remove exactly the labeled test set with bounded CLI calls and rediscovery."""
    report = dict(attempted=False, discovered=[], removed=[], remaining=[], errors=[])
    try:
        identities = command('ps', '-aq', '--filter', f'label={label}={owner}', timeout=10).decode().split()
        report['discovered'] = identities
        if len(identities) > 96 or any(not re.fullmatch('[a-f0-9]{12,64}', value) for value in identities):
            raise RuntimeError('Cleanup identity set outside reviewed bound')
        if identities:
            raw = command('inspect', '--format={{.Id}}\t{{json .Config.Labels}}', *identities, timeout=20)
            rows = raw.decode().splitlines()
            if len(rows) != len(identities):
                raise RuntimeError('Cleanup inspection count mismatch')
            for row in rows:
                _, separator, labels_raw = row.partition('\t')
                labels = json.loads(labels_raw) if separator else {}
                if labels.get(label) != owner:
                    raise RuntimeError('Cleanup ownership mismatch')
            report['attempted'] = True
            command('rm', '-f', *identities, timeout=30)
            report['removed'] = identities
    except Exception as exc:
        report['errors'].append(type(exc).__name__)
    try:
        report['remaining'] = command(
            'ps', '-aq', '--filter', f'label={label}={owner}', timeout=10
        ).decode().split()
    except Exception as exc:
        report['errors'].append(type(exc).__name__)
        report['remaining'] = ['rediscovery-failed']
    report['complete'] = not report['errors'] and not report['remaining']
    return report

BPP_IDENTITY_SOURCE = r'''
def bpp_identity(launcher,compiler):
 if launcher.stat().st_size>65536 or compiler.stat().st_size>32*1024**2:
  raise RuntimeError('Bounded native B++ ELF identity required')
 wrapper=launcher.read_bytes()
 binary=compiler.read_bytes()
 if len(wrapper)>65536 or len(binary)>32*1024**2 or binary[:4]!=b'\x7fELF':
  raise RuntimeError('Bounded native B++ ELF identity required')
 return {'version':'binary-sha256:'+hashlib.sha256(binary).hexdigest(),'exit':0,
         'launcherSha256':hashlib.sha256(wrapper).hexdigest(),'compilerPath':str(compiler)}
'''

VERSION_PROBE = r'''
import hashlib,json,pathlib,shutil,subprocess
''' + BPP_IDENTITY_SOURCE + r'''
result={}
commands={'c':['/usr/bin/gcc','--version'],'cpp':['/usr/bin/g++','--version'],
 'python':['/usr/bin/python3','--version'],'java':['/usr/bin/java','-version'],
 'javascript':['/usr/local/bin/node','--version']}
for lang,argv in commands.items():
 if not pathlib.Path(argv[0]).is_file(): result[lang]={'missing':argv[0]}; continue
 p=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=5)
 result[lang]={'version':p.stdout.decode(errors='replace').splitlines()[0][:160],'exit':p.returncode}
bpp=shutil.which('bpp')
# This probe supports the reviewed installed v13 layout. Do not hash the shell
# launcher as though it were the native compiler, nor infer a different binary.
compiler=pathlib.Path('/usr/local/libexec/bpp/v13_stage1')
result['bpp']=bpp_identity(pathlib.Path(bpp),compiler) if bpp and compiler.is_file() else {'missing':'bpp native v13 ELF'}
result['tools']={p:bool(shutil.which(p)) for p in ['javac','nasm','ld']}
print(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--controller-image', required=True)
    parser.add_argument('--runtime-image', required=True)
    parser.add_argument('--docker-socket', required=True, type=Path,
                        help='non-default Unix socket for a dedicated disposable Docker daemon')
    parser.add_argument('--daemon-id-sha256', required=True,
                        help='SHA-256 of `docker --host ... info --format {{.ID}}`')
    parser.add_argument('--harness-sha256', required=True,
                        help='SHA-256 of this reviewed outer harness file')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--language', choices=['all','bpp','c','cpp','python','java','javascript'], default='all')
    parser.add_argument('--suite',choices=['mechanics','freshman','freshman-candidate',
        'freshman-draft','freshman-draft-candidate','freshman-slow','bpp-diagnostic'],default='mechanics')
    parser.add_argument('--repetition',type=int,choices=range(1,11),default=1)
    args = parser.parse_args()
    root = require_private_root(args.root)
    candidate=args.suite in ('freshman-candidate','freshman-draft-candidate')
    slow=args.suite=='freshman-slow'
    draft=args.suite in ('freshman-draft','freshman-draft-candidate','freshman-slow')
    if candidate and args.language!='bpp': raise SystemExit('Candidate overlay is B++ only')
    if slow and args.language!='python': raise SystemExit('Slow comparison is Python only')
    if (args.suite=='mechanics' and args.language not in ('all','bpp')) or (args.suite in ('freshman','freshman-draft') and args.language=='all'):
        raise SystemExit('Use one runtime per bounded freshman pass')
    if args.suite=='bpp-diagnostic' and args.language!='bpp': raise SystemExit('B++ diagnostic requires B++')
    controller_timeout = controller_timeout_seconds(args.suite,args.language)
    reference_suite=args.suite in ('freshman','freshman-candidate','freshman-draft',
        'freshman-draft-candidate','freshman-slow','bpp-diagnostic')
    probe_name=('verify_freshman_slow.py' if slow else
                'verify_freshman_measurements.py' if reference_suite else 'verify_runtime_matrix.py')
    if not args.execute or args.root!=root or root.parent != Path('/tmp') or not re.fullmatch(r'webcompiler-launcher-test\.[A-Za-z0-9]+', root.name):
        raise SystemExit('Explicit isolated opt-in and owned temporary root required')
    fixed_input_identities=verify_fixed_inputs(
        root,
        suite=args.suite,
        harness_sha256=args.harness_sha256,
    )
    docker_socket, daemon_id_sha256 = bind_dedicated_daemon(
        args.docker_socket,
        args.daemon_id_sha256,
    )
    for image in (args.controller_image, args.runtime_image):
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', image): raise SystemExit('Immutable image required')
        if command('image', 'inspect', '--format={{.Id}}', image).decode().strip() != image:
            raise SystemExit('Exact existing image required')
    before = capacity(); owner = uuid.uuid4().hex
    candidate_identity=None;candidate_mounts=[]
    if candidate:
        from bpp_candidate_overlay import IMAGE,prepare_overlay
        if args.runtime_image!=IMAGE: raise RuntimeError('Exact candidate base image required')
        candidate_identity=prepare_overlay(root)
        candidate_mounts=['--mount',f'type=bind,src={root/"bpp-candidate"},dst={root/"bpp-candidate"},readonly']
        for script in ('bpp_candidate_overlay.py','probe_bpp_candidate.py'):
            candidate_mounts.extend(['--mount',f'type=bind,src={root/script},dst=/{script},readonly'])
    label = 'webcompiler.isolated-runtime-matrix'
    evidence=None; primary_error=None; primary_traceback=None
    try:
        versions_raw = command('run', '--rm', '--pull=never', '--label', f'{label}={owner}',
            '--network=none', '--read-only', '--user=65534:65534', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--memory=512m', '--memory-swap=512m',
            '--cpus=0.5', '--pids-limit=48', '--no-healthcheck', '--log-driver=none',
            '--tmpfs=/tmp:rw,nosuid,nodev,size=16m', '--entrypoint=/usr/bin/python3',
            args.runtime_image, '-I', '-c', VERSION_PROBE, timeout=35)
        if len(versions_raw) > 8192: raise RuntimeError('Version report cap')
        versions = json.loads(versions_raw)
        if candidate:
            from bpp_candidate_overlay import bind_base_identity
            candidate_identity=bind_base_identity(candidate_identity,args.runtime_image,versions['bpp'])
        print(json.dumps(dict(scope='isolated-runtime-discovery', image=args.runtime_image, versions=versions)), flush=True)
        if any('missing' in versions[k] or versions[k]['exit'] != 0 for k in ('c','cpp','python','java','javascript','bpp')) or not all(versions['tools'].values()):
            raise RuntimeError('Existing image lacks required toolchains; no installation attempted')
        with (root/'versions.json').open('x', encoding='utf-8') as stream: json.dump(versions, stream)
        source = root/'candidate'; source.mkdir(mode=0o755)
        with tarfile.open(root/'measured-app-source.tar.gz', mode='r:gz') as archive:
            members = archive.getmembers()
            if len(members) > 250 or sum(m.size for m in members) > 8*1024**2: raise RuntimeError('Source archive cap')
            for member in members:
                path = Path(member.name)
                if path.is_absolute() or '..' in path.parts or path.parts[0] != 'app' or not (member.isfile() or member.isdir()):
                    raise RuntimeError('Invalid source archive')
            archive.extractall(source, filter='data')
        if reference_suite:
            with tarfile.open(root/'freshman-package.tar.gz',mode='r:gz') as archive:
                members=archive.getmembers()
                if len(members)>150 or sum(m.size for m in members)>4*1024**2: raise RuntimeError('Reference archive cap')
                for member in members:
                    path=Path(member.name)
                    if path.is_absolute() or '..' in path.parts or path.parts[:2]!=('tools','freshman_contest') or not (member.isfile() or member.isdir()):
                        raise RuntimeError('Invalid reference archive')
                archive.extractall(source,filter='data')
        root.chmod(0o700)
        for path in source.rglob('*'): path.chmod(0o755 if path.is_dir() else 0o444)
        work = root/'work'; work.mkdir(mode=0o700); work.chmod(0o700)
        require_private_root(work)
        identity = command('create', '--pull=never', '--label', f'{label}={owner}',
            '--name', 'webcompiler-runtime-controller-'+owner, '--network=none', '--read-only',
            '--user=0:0', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--memory=384m', '--memory-swap=384m', '--cpus=0.5', '--pids-limit=48',
            '--no-healthcheck', '--log-driver=none', '--workdir=/candidate',
            '--mount', f'type=bind,src={source},dst=/candidate,readonly',
            '--mount', f'type=bind,src={root/probe_name},dst=/probe.py,readonly',
            *(['--mount', f'type=bind,src={root/"verify_freshman_measurements.py"},dst=/verify_freshman_measurements.py,readonly']
              if slow else []),
            '--mount', f'type=bind,src={root/"verify_runtime_matrix.py"},dst=/verify_runtime_matrix.py,readonly',
            '--mount', f'type=bind,src={root/"versions.json"},dst=/versions.json,readonly',
            '--mount', f'type=bind,src={work},dst={work}',
            '--mount', f'type=bind,src={docker_socket},dst=/var/run/docker.sock',
            *candidate_mounts,
            '-e', 'PYTHONPATH=/candidate', '-e', 'PYTHONDONTWRITEBYTECODE=1',
            '-e', 'ENVIRONMENT=development', '-e', 'SECRET_KEY=isolated-matrix-not-production-secret-2026',
            '-e', 'DATABASE_URL=sqlite:///:memory:', '-e', 'AUTO_INITIALIZE_DB=false',
            '-e', 'EMBEDDED_EXECUTION_WORKER=false', '-e', 'REDIS_URL=',
            '--entrypoint=/opt/venv/bin/python', args.controller_image, '/probe.py',
            '--image', args.runtime_image, '--owner', owner, '--workspace', str(work), '--language', args.language,
            *(['--repetition',str(args.repetition)] if reference_suite else []),
            *(['--diagnostic'] if args.suite=='bpp-diagnostic' else []),
            *(['--candidate'] if candidate else []),
            *(['--draft-corpus'] if draft else []), '--execute').decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', identity): raise RuntimeError('Controller identity invalid')
        timed_out=False
        controller_started=time.monotonic()
        try:
            result = subprocess.run(['docker','start','-a',identity], capture_output=True,
                                    timeout=controller_timeout)
        except subprocess.TimeoutExpired as exc:
            timed_out=True
            result=SimpleNamespace(returncode=124,stdout=exc.stdout or b'',stderr=exc.stderr or b'')
        if len(result.stdout)+len(result.stderr) > 131072: raise RuntimeError('Controller report cap')
        # Persist exact evidence before temporary container cleanup, even for a
        # failed matrix. This report does not itself approve a contest policy.
        elapsed=time.monotonic()-controller_started
        evidence=dict(version=1,owner=owner,suite=args.suite,repetition=args.repetition,
            **controller_watchdog_evidence(args.suite,args.language,elapsed,timed_out),
            host=dict(system=platform.system(),kernel=platform.release(),architecture=platform.machine(),cpuCount=os.cpu_count()),
            dedicatedDockerDaemonIdSha256=daemon_id_sha256,
            fixedInputIdentities=fixed_input_identities,
            controllerImage=args.controller_image,runtimeImage=args.runtime_image,
            sourceArchiveSha256=hashlib.sha256((root/'measured-app-source.tar.gz').read_bytes()).hexdigest(),
            scriptsSha256={name:hashlib.sha256((root/name).read_bytes()).hexdigest()
                           for name in set(('run_isolated_runtime_matrix.py','verify_runtime_matrix.py',probe_name))},
            versions=versions,capacityBefore=before,capacityBeforeCleanup=capacity(),controllerExitCode=result.returncode,
            stdout=result.stdout.decode(errors='replace'),stderr=result.stderr.decode(errors='replace'))
        if reference_suite:
            evidence['referenceArchiveSha256']=hashlib.sha256((root/'freshman-package.tar.gz').read_bytes()).hexdigest()
        if slow:
            evidence['scriptsSha256']['verify_freshman_measurements.py']=hashlib.sha256(
                (root/'verify_freshman_measurements.py').read_bytes()).hexdigest()
        if candidate:
            evidence['candidateOverlay']=candidate_identity
            for name in ('bpp_candidate_overlay.py','probe_bpp_candidate.py'):
                evidence['scriptsSha256'][name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
        print(result.stdout.decode(errors='replace'), flush=True)
        if result.returncode:
            print(result.stderr.decode(errors='replace'), flush=True)
            raise RuntimeError('Runtime matrix incomplete')
    except BaseException as exc:
        primary_error=exc; primary_traceback=exc.__traceback__
    finally:
        cleanup=cleanup_owned_containers(label,owner)
    if evidence is not None:
        evidence['cleanup']=cleanup
        try:
            evidence['capacityAfterCleanup']=capacity()
        except Exception as exc:
            evidence['capacityAfterCleanupError']=type(exc).__name__
        with (root/'matrix-report.json').open('x',encoding='utf-8') as stream:
            json.dump(evidence,stream,ensure_ascii=False,indent=2)
    if not cleanup['complete']:
        cleanup_error=RuntimeError('Owned runtime-matrix cleanup incomplete')
        if primary_error is None:
            raise cleanup_error
        primary_error.add_note(str(cleanup_error))
    if primary_error is not None:
        raise primary_error.with_traceback(primary_traceback)
    print(json.dumps(dict(capacityBefore=before,capacityAfterCleanup=evidence.get('capacityAfterCleanup'),
        cleanup=cleanup)),flush=True)


if __name__ == '__main__': main()
