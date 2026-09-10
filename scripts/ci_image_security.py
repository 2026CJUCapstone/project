#!/usr/bin/env python3
"""Build all three application images and scan their immutable local IDs.

Uses an already provisioned bounded builder. Does not start application services,
push images, deploy, or silently accept a base-image scan as application evidence.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from scan_image import COMMIT, SHA, ScanError, run_scan
from verify_build_builder import Config, verify

ROOT = Path(__file__).resolve().parents[1]
ROLES = ('backend', 'frontend', 'sandbox')


def build_command(role, commit, compiler_ref, builder, iidfile):
    if role not in ROLES or not COMMIT.fullmatch(commit) or not COMMIT.fullmatch(compiler_ref):
        raise ScanError('Invalid build role or immutable source revision')
    context = ROOT / ('runtime' if role == 'sandbox' else role)
    dockerfile = context / ('docker/Dockerfile' if role == 'sandbox' else 'Dockerfile')
    command = ['docker', 'buildx', 'build', '--builder', builder, '--load',
        '--platform', 'linux/amd64', '--iidfile', str(iidfile),
        '--label', 'io.webcompiler.source-sha=' + commit,
        '--label', 'io.webcompiler.image-role=' + role]
    if role == 'frontend':
        for value in ('ENVIRONMENT=production', 'DEPLOY_SHA=' + commit,
                'VITE_APP_BASE_PATH=/webcompiler/', 'VITE_API_URL=/webcompiler',
                'FRONTEND_API_UPSTREAM=api-proxy:8080'):
            command.extend(['--build-arg', value])
    if role == 'sandbox':
        command.extend(['--shm-size=2g', '--build-arg', 'BPP_REF=' + compiler_ref])
    return command + ['-f', str(dockerfile), str(context)]


def build_and_scan(*, commit, trivy, output, cache):
    if not COMMIT.fullmatch(commit):
        raise ScanError('Exact checked-out commit required')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if head != commit:
        raise ScanError('Checkout does not match the requested source commit')
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=ROOT, text=True).strip():
        raise ScanError('A clean checkout including untracked source is required')
    subprocess.run(['git', 'diff', '--exit-code', 'HEAD', '--'], cwd=ROOT, check=True,
        stdout=subprocess.DEVNULL)
    compiler_ref = (ROOT / 'runtime/bpp-ref.txt').read_text().strip()
    if not COMMIT.fullmatch(compiler_ref):
        raise ScanError('Pinned compiler source required')
    config = Config.from_environment()
    if not config.container_id:
        raise ScanError('Explicitly bound build container required')
    verify(config)
    output = Path(output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    results, image_ids = {}, set()
    for role in ROLES:
        verify(config)
        iidfile = output / (role + '.iid')
        subprocess.run(build_command(role, commit, compiler_ref, config.name, iidfile),
            cwd=ROOT, check=True, timeout=2400)
        verify(config)
        image_id = iidfile.read_text().strip()
        if not SHA.fullmatch(image_id) or image_id in image_ids:
            raise ScanError('Each application role requires a distinct immutable built image')
        image_ids.add(image_id)
        # The sandbox's second source repository is independent of the web SHA.
        if role == 'sandbox':
            metadata = json.loads(subprocess.check_output(
                ['docker', 'image', 'inspect', image_id], text=True, timeout=30))
            if len(metadata) != 1 or metadata[0]['Id'] != image_id or metadata[0]['Config']['Labels'].get('io.bpp.ref') != compiler_ref:
                raise ScanError('Built sandbox compiler revision mismatch')
        summary = run_scan(trivy=trivy, target=image_id, source='docker', scope='application',
            role=role, commit=commit, output=output/role, cache=cache)
        manifest = output/role/'manifest.json'
        results[role] = {'imageId': image_id, 'policyPassed': summary['policyPassed'],
            'manifestSha256': hashlib.sha256(manifest.read_bytes()).hexdigest()}
    receipt = {'schemaVersion': 1, 'sourceCommit': commit, 'compilerCommit': compiler_ref,
        'roles': results, 'policyPassed': all(value['policyPassed'] for value in results.values())}
    (output/'application-images.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--trivy', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--cache-dir', required=True)
    args = parser.parse_args()
    try:
        receipt = build_and_scan(commit=args.commit, trivy=args.trivy,
            output=args.output_dir, cache=args.cache_dir)
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        print('Application image security failed: ' + type(exc).__name__)
        return 2
    print(json.dumps(receipt))
    return 0 if receipt['policyPassed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
