"""Bounded Node compatibility probe for the final Alpine sandbox stage.

This deliberately excludes only B++ checkout, copied B++ artifacts, and its two
installed-compiler gates.  It is not a complete sandbox image or judge/queue
test. The caller owns/verifies the builder and cleans its image tag.
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
test "$(npm --version)" = 11.19.1
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
    """Retain the npm builder prefix and final runtime, omitting only B++ work."""
    from_lines = [line for line in source.splitlines() if line.startswith('FROM ')]
    if len(from_lines) != 3:
        raise ValueError('Exact three-stage product Dockerfile required')
    if (not from_lines[0].startswith('FROM node:')
            or 'bookworm-slim@sha256:' not in from_lines[0]
            or not from_lines[0].endswith(' AS node-runtime')):
        raise ValueError('Pinned Node npm-builder source stage required')
    if (not from_lines[1].startswith('FROM ubuntu:26.04@sha256:')
            or not from_lines[1].endswith(' AS bpp-build')):
        raise ValueError('Exact B++ builder stage required')
    if (not from_lines[2].startswith('FROM node:')
            or '-alpine@sha256:' not in from_lines[2]
            or not from_lines[2].endswith(' AS sandbox-runtime')):
        raise ValueError('Exact final Alpine sandbox stage required')

    bpp_stage = source.index('\nFROM ', source.index(from_lines[0])) + 1
    final_stage = source.index('\nFROM ', bpp_stage) + 1
    builder = source[bpp_stage:final_stage]
    runtime = source[final_stage:]
    compiler_boundary = '\nARG BPP_REPO='
    if builder.count(compiler_boundary) != 1:
        raise ValueError('Exact product compiler-stage boundary required')
    npm_builder = source[:bpp_stage] + builder.split(compiler_boundary, 1)[0]
    if ('COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node\n' not in npm_builder
            or 'mkdir -p /usr/local/lib/node_modules/npm' not in npm_builder
            or 'tar -xzf /tmp/npm.tgz --strip-components=1 -C /usr/local/lib/node_modules/npm' not in npm_builder
            or 'test "$(npm --version)" = 11.19.1;' not in npm_builder):
        raise ValueError('Verified npm builder prefix required before B++ checkout')
    if any(value in npm_builder for value in ('git clone', 'compiler-patches', '/opt/Bpp')):
        raise ValueError('Node probe must not include compiler checkout')
    if runtime.count('\nWORKDIR /sandbox\n') != 1:
        raise ValueError('Exact final runtime packaging boundary required')
    if ('COPY --from=bpp-build /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm\n'
            not in runtime):
        raise ValueError('Final Alpine stage must copy the verified npm tree')

    # This narrow Node probe has no B++ installation. Remove only exact B++
    # copies and both mandatory installed-compiler gates; reject any drift
    # rather than broadly dropping Python or final-runtime instructions.
    for instruction in (
        'COPY --from=bpp-build /usr/local/bin/bpp /usr/local/bin/bpp\n',
        'COPY --from=bpp-build /usr/local/libexec/bpp /usr/local/libexec/bpp\n',
        'COPY --from=bpp-build /usr/local/share/bpp /usr/local/share/bpp\n',
        'COPY --from=bpp-build /usr/local/share/bpp-build-info.txt /usr/local/share/bpp-build-info.txt\n',
        'COPY sandbox/verify_bpp_runtime.py /usr/local/share/verify_bpp_runtime.py\n',
        'COPY sandbox/verify_bpp_exploration.py /usr/local/share/verify_bpp_exploration.py\n',
        'RUN python3 -I /usr/local/share/verify_bpp_runtime.py\n',
        'RUN python3 -I /usr/local/share/verify_bpp_exploration.py\n',
    ):
        if runtime.splitlines(keepends=True).count(instruction) != 1:
            raise ValueError('Exact B++-only copy or gate instruction required')
        runtime = runtime.replace(instruction, '', 1)
    if any(value in runtime for value in ('/usr/local/bin/bpp', '/usr/local/libexec/bpp',
                                           '/usr/local/share/bpp', 'verify_bpp_')):
        raise ValueError('B++ artifacts or gates survived the Node-only probe')
    # Preserve the actual Alpine stage and non-B++ packaging instructions.
    return npm_builder + runtime + '''
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
    print('Starting actual final-Alpine Node build (B++ work excluded)', flush=True)
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
            print('Actual Alpine Node24/nonroot/run.sh checks passed in '
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
