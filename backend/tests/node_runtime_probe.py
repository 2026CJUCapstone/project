"""Bounded Linux Node compatibility probe using the real runtime Dockerfile prefix.

This deliberately excludes B++ checkout/build and is not a complete sandbox image
or judge/queue test. The caller owns/verifies the builder and cleans its image tag.
"""
import json
import shutil
import subprocess
import time


SMOKE = r'''#!/bin/bash
set -euo pipefail
test "$(id -un)" = sandboxuser
test "$(id -u)" != 0
test "$(node --version)" = v24.21.0
test "$(nodejs --version)" = v24.21.0
npm --version
npx --version
ldd /usr/local/bin/node > /tmp/node-ldd.txt
! grep -q 'not found' /tmp/node-ldd.txt
for name in hello sum unicode bigint runtime_error; do
    /usr/local/bin/run.sh compile javascript "/audit/$name.js"
done
test "$(/usr/local/bin/run.sh run javascript /audit/hello.js)" = 'Hello, World!'
test "$(/usr/local/bin/run.sh run javascript /audit/sum.js /audit/stdin.txt)" = 42
/usr/local/bin/run.sh run javascript /audit/unicode.js /audit/unicode.txt > /tmp/unicode.out
cmp /audit/unicode.txt /tmp/unicode.out
test "$(/usr/local/bin/run.sh run javascript /audit/bigint.js)" = 9007199254741000
if /usr/local/bin/run.sh compile javascript /audit/syntax_error.js > /tmp/ce.out 2>&1; then
    echo 'Syntax error unexpectedly compiled' >&2
    exit 1
fi
grep -q SyntaxError /tmp/ce.out
if /usr/local/bin/run.sh run javascript /audit/runtime_error.js > /tmp/re.out 2>&1; then
    echo 'Runtime error unexpectedly succeeded' >&2
    exit 1
fi
grep -q 'fixture runtime failure' /tmp/re.out
printf 'NODE_RUNTIME_PROBE_OK\n'
'''


def dockerfile_prefix(source):
    marker = '\nARG BPP_REPO='
    if source.count(marker) != 1:
        raise ValueError('Exact product compiler-stage boundary required')
    prefix = source.split(marker, 1)[0]
    if 'AS node-runtime\n' not in prefix or 'COPY --from=node-runtime ' not in prefix:
        raise ValueError('Product pinned Node copy stage required')
    tail_marker = '\nWORKDIR /sandbox\n'
    if source.count(tail_marker) != 1:
        raise ValueError('Exact product runtime packaging boundary required')
    tail = tail_marker + source.split(tail_marker, 1)[1]
    if source.index(tail_marker) <= source.index(marker):
        raise ValueError('Runtime packaging must follow the compiler stage')
    # Preserve both real stages; only the B++ checkout/build in between is omitted.
    return prefix + tail + '''
COPY fixtures /audit
RUN --network=none /bin/bash /audit/smoke.sh
'''


def run(case, *, source_root, workdir, env, builder_name, container_id, nonce,
        tag, command, call, verify, limit=900):
    context = workdir / 'node-runtime-context'
    context.mkdir()
    source = (source_root / 'runtime/docker/Dockerfile').read_text(encoding='utf-8')
    (context / 'Dockerfile').write_text(dockerfile_prefix(source), encoding='utf-8')
    (context / 'sandbox').mkdir()
    shutil.copyfile(source_root / 'runtime/sandbox/run.sh', context / 'sandbox/run.sh')
    shutil.copytree(source_root / 'backend/tests/fixtures/node-runtime', context / 'fixtures')
    (context / 'fixtures/smoke.sh').write_text(SMOKE, encoding='utf-8')
    verify()
    log_path = workdir / 'node-runtime-build.log'
    print('Starting actual runtime-prefix Node build (B++ build excluded)', flush=True)
    arguments = ['docker', 'buildx', 'build', '--builder', builder_name, '--load',
        '--progress', 'plain', '--label', 'io.webcompiler.audit.nonce=' + nonce,
        '--tag', tag, str(context)]
    with log_path.open('w+', encoding='utf-8', errors='replace') as log:
        process = subprocess.Popen(arguments, env=env, stdout=log, stderr=subprocess.STDOUT)
        started = last_report = time.monotonic()
        try:
            while process.poll() is None:
                free = shutil.disk_usage('/var/lib/docker').free
                case.assertGreater(free, 8 * 1024**3, 'Node probe disk safety floor reached')
                case.assertLess(time.monotonic() - started, limit, 'Node probe build time exceeded')
                if time.monotonic() - last_report >= 30:
                    print('Node prefix build elapsed=' + str(int(time.monotonic() - started))
                        + 's; disk-free-MiB=' + str(free // 1024**2), flush=True)
                    last_report = time.monotonic()
                time.sleep(1)
            log.seek(0)
            output = log.read()
            case.assertEqual(process.returncode, 0, output[-10000:])
            case.assertIn('NODE_RUNTIME_PROBE_OK', output)
            print('Actual glibc Node24/nonroot/run.sh checks passed in '
                + str(round(time.monotonic() - started, 1)) + 's', flush=True)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                current = json.loads(call(['container', 'inspect', container_id]))[0]
                case.assertIn('WEBCOMPILER_AUDIT_NONCE=' + nonce, current['Config']['Env'])
                command(['container', 'stop', '--time', '5', container_id], timeout=15)
    verify()
    image = json.loads(call(['image', 'inspect', tag]))[0]
    case.assertEqual(image['Config']['Labels']['io.webcompiler.audit.nonce'], nonce)
    case.assertEqual(image['Config']['User'], 'sandboxuser')
    case.assertEqual(image['Config']['Entrypoint'], ['/usr/local/bin/run.sh'])
