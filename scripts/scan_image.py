#!/usr/bin/env python3
"""Scan one immutable image with pinned Trivy; never start the target image.

Reports contain package inventory, not image environment/history. Application
scope additionally requires the build's source SHA label. This is not a signed
attestation, complete compiler inventory, or proof of runtime exploitability.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import unquote

VERSION = '0.74.0'
SHA = re.compile(r'sha256:[0-9a-f]{64}\Z')
COMMIT = re.compile(r'[0-9a-f]{40}\Z')
REMOTE = re.compile(r'[a-z0-9][a-z0-9./_-]*(?::[0-9]+)?/[a-z0-9][a-z0-9./_-]*@sha256:[0-9a-f]{64}\Z')
SEVERITIES = {'UNKNOWN', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'}
LIMIT = 32 * 1024**2


class ScanError(ValueError):
    pass


def read_json(path):
    with Path(path).open('rb') as handle:
        raw = handle.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ScanError('Report exceeds the input limit')
    return json.loads(raw)


def validate_target(target, source, scope, commit, role=None):
    if source == 'remote' and not REMOTE.fullmatch(target):
        raise ScanError('Remote scanning requires an explicit registry and digest')
    if source == 'remote' and not any(character in target.split('/', 1)[0] for character in '.:') and not target.startswith('localhost/'):
        raise ScanError('Explicit registry hostname required')
    if source == 'docker' and not SHA.fullmatch(target):
        raise ScanError('Local scanning requires the full immutable image ID')
    if source not in {'remote', 'docker'} or scope not in {'base', 'application'}:
        raise ScanError('Unsupported scan source or scope')
    if scope == 'application' and (source != 'docker' or not COMMIT.fullmatch(commit or '')):
        raise ScanError('Built application scanning requires an image ID and exact commit')
    if scope == 'base' and commit:
        raise ScanError('Base scans cannot attest an application commit')
    if scope == 'application' and role not in {'backend', 'frontend', 'sandbox'}:
        raise ScanError('Built application role is required')
    if scope == 'base' and role is not None:
        raise ScanError('Base scans cannot attest an application role')


def summarize(report, *, target, source, scope, commit=None, role=None):
    validate_target(target, source, scope, commit, role)
    if report.get('SchemaVersion') != 2 or report.get('ArtifactType') != 'container_image':
        raise ScanError('A Trivy v2 container image report is required')
    if report.get('ArtifactName') != target:
        raise ScanError('Scanned artifact does not match the requested image')
    metadata = report.get('Metadata', {})
    image_id = metadata.get('ImageID', '')
    if not SHA.fullmatch(image_id) or (source == 'docker' and image_id != target):
        raise ScanError('Scanned immutable image ID mismatch')
    if source == 'remote':
        digest = target.rsplit('@', 1)[1]
        if not any(ref.endswith('@' + digest) for ref in metadata.get('RepoDigests', [])):
            raise ScanError('Scanned registry digest mismatch')
    operating_system = metadata.get('OS', {})
    if not operating_system.get('Family') or not operating_system.get('Name'):
        raise ScanError('Image OS inventory was not detected')
    config = metadata.get('ImageConfig', {})
    if config.get('os') != 'linux' or config.get('architecture') != 'amd64':
        raise ScanError('Expected the Linux amd64 image')
    if scope == 'application':
        labels = config.get('config', {}).get('Labels', {})
        if labels.get('io.webcompiler.source-sha') != commit:
            raise ScanError('Built image is not bound to the requested source commit')
        if labels.get('io.webcompiler.image-role') != role:
            raise ScanError('Built image is not bound to the requested role')
    counts = Counter()
    package_count = 0
    os_packages = 0
    results = report.get('Results')
    if not isinstance(results, list) or not results:
        raise ScanError('Image package results are missing')
    for result in results:
        if result.get('Class') not in {'os-pkgs', 'lang-pkgs'}:
            raise ScanError('Unexpected result class')
        packages = result.get('Packages')
        if not isinstance(packages, list) or not packages:
            raise ScanError('Full installed package inventory is required')
        for package in packages:
            if not package.get('Name') or not package.get('Version'):
                raise ScanError('Installed package name or version is missing')
        package_count += len(packages)
        if result['Class'] == 'os-pkgs':
            os_packages += len(packages)
        for finding in result.get('Vulnerabilities') or []:
            if finding.get('Severity') not in SEVERITIES or not finding.get('VulnerabilityID'):
                raise ScanError('Malformed vulnerability result')
            counts[finding['Severity']] += 1
    if not os_packages:
        raise ScanError('No installed OS package inventory')
    # OS inventory alone cannot establish that installed application libraries
    # were detected. The frontend ships static assets: its JS graph is checked
    # separately against package-lock.json, not inferred from Nginx packages.
    required = {'backend': 'pkg:pypi/fastapi@', 'sandbox': 'pkg:npm/npm@'}.get(role)
    if required and not any(result['Class'] == 'lang-pkgs' and any(
            package.get('Identifier', {}).get('PURL', '').startswith(required)
            for package in result['Packages']) for result in results):
        raise ScanError('Expected installed application library inventory is missing')
    # No implicit ignore list, VEX waiver or ignore-unfixed policy. Unknown
    # severity is an unresolved finding, never silently a passing result.
    blocked = bool(operating_system.get('EOSL') or any(counts[level] for level in ('UNKNOWN', 'HIGH', 'CRITICAL')))
    safe = {key: report[key] for key in ('SchemaVersion', 'ArtifactName', 'ArtifactType')}
    safe['Metadata'] = {'ImageID': image_id, 'OS': operating_system,
        'ImageConfig': {'architecture': 'amd64', 'os': 'linux'}}
    safe['Results'] = results
    summary = {'schemaVersion': 1, 'scope': scope, 'sourceCommit': commit, 'role': role,
        'target': target, 'imageId': image_id, 'scanner': {'name': 'Trivy', 'version': VERSION},
        'os': operating_system, 'installedPackageEntries': package_count,
        'findingEntriesBySeverity': dict(sorted(counts.items())), 'policyPassed': not blocked,
        'policy': 'reject-unknown-high-critical-and-eol-no-waivers'}
    return safe, summary


def verify_inventory(report, inventory):
    """Compare every detected package PURL, including version, after conversion.

    Trivy can coalesce identical versions from several paths into one component.
    Compare unique identities, not occurrence counts or optional graph edges.
    """
    expected = set()
    for result in report['Results']:
        for package in result['Packages']:
            purl = package.get('Identifier', {}).get('PURL')
            if not isinstance(purl, str) or not purl.startswith('pkg:') or '@' not in purl:
                raise ScanError('Installed package identity is missing')
            expected.add(purl)
    if inventory.get('bomFormat') != 'CycloneDX' or not inventory.get('components'):
        raise ScanError('Installed-image CycloneDX inventory is missing')
    component = inventory.get('metadata', {}).get('component', {})
    properties = component.get('properties', [])
    if (component.get('type') != 'container' or component.get('name') != report['ArtifactName']
            or {'name': 'aquasecurity:trivy:ImageID', 'value': report['Metadata']['ImageID']} not in properties):
        raise ScanError('CycloneDX image identity mismatch')
    observed = set()
    pending = list(inventory['components'])
    while pending:
        component = pending.pop()
        pending.extend(component.get('components', []))
        purl = component.get('purl')
        if purl:
            if not isinstance(purl, str) or purl not in expected:
                raise ScanError('Unexpected CycloneDX package identity')
            version = unquote(purl.split('?', 1)[0].split('#', 1)[0].rsplit('@', 1)[-1])
            if component.get('version') != version:
                raise ScanError('CycloneDX package version mismatch')
            observed.add(purl)
        elif component.get('type') not in {'operating-system', 'application', 'container'}:
            raise ScanError('CycloneDX library identity is missing')
    if observed != expected:
        raise ScanError('CycloneDX package inventory is incomplete')
    return len(expected)


def run_scan(*, trivy, target, source, scope, commit, output, cache, role=None):
    validate_target(target, source, scope, commit, role)
    output, cache, trivy = Path(output).resolve(), Path(cache).resolve(), Path(trivy).resolve()
    if output.exists():
        raise ScanError('Refusing to overwrite an existing report directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    # A fresh cwd plus empty config/ignore files prevents a repository's
    # trivy.yaml/.trivyignore or caller TRIVY_* filters changing the gate.
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('TRIVY_')}
    env['TRIVY_DISABLE_TELEMETRY'] = 'true'
    with tempfile.TemporaryDirectory(prefix='image-scan-', dir=output.parent) as folder:
        scratch = Path(folder)
        empty_config, empty_ignore = scratch/'config.json', scratch/'ignore'
        empty_config.write_text('{}', encoding='utf-8')
        empty_ignore.write_text('', encoding='utf-8')
        def command(arguments, timeout=660):
            with (scratch/'scanner.log').open('ab') as log:
                result = subprocess.run([str(trivy), *arguments], env=env, cwd=scratch,
                    stdout=log, stderr=log, timeout=timeout)
            if result.returncode:
                raise ScanError('Scanner failed; no successful manifest was produced')
        version = subprocess.run([str(trivy), 'version', '--format', 'json'], env=env,
            cwd=scratch, capture_output=True, text=True, timeout=15, check=True)
        if json.loads(version.stdout).get('Version') != VERSION:
            raise ScanError('Pinned Trivy version required')
        raw = scratch/'raw.json'
        command(['image', '--image-src', source, '--platform', 'linux/amd64',
            '--scanners', 'vuln', '--pkg-types', 'os,library', '--list-all-pkgs',
            '--parallel', '1', '--disable-telemetry', '--timeout', '10m',
            '--config', str(empty_config), '--ignorefile', str(empty_ignore),
            '--severity', ','.join(sorted(SEVERITIES)), '--ignore-unfixed=false',
            '--format', 'json', '--output', str(raw), '--cache-dir', str(cache),
            '--exit-code', '0', '--exit-on-eol', '0', '--quiet', target])
        safe, summary = summarize(read_json(raw), target=target, source=source, scope=scope, commit=commit, role=role)
        db = read_json(cache/'db/metadata.json')
        updated = datetime.fromisoformat(db['UpdatedAt'].replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - updated).total_seconds()
        if db.get('Version') != 2 or not 0 <= age <= 48 * 3600:
            raise ScanError('Fresh vulnerability database required (at most 48 hours)')
        summary['database'] = {'version': db['Version'], 'updatedAt': db['UpdatedAt']}
        with trivy.open('rb') as executable:
            summary['scanner']['binarySha256'] = hashlib.file_digest(executable, 'sha256').hexdigest()
        sanitized = scratch/'report.json'
        sanitized.write_text(json.dumps(safe, ensure_ascii=False), encoding='utf-8')
        sbom = scratch/'sbom.cdx.json'
        command(['convert', '--format', 'cyclonedx', '--list-all-pkgs', '--config', str(empty_config),
            '--output', str(sbom), str(sanitized)], timeout=60)
        inventory = read_json(sbom)
        summary['uniquePackageIdentities'] = verify_inventory(safe, inventory)
        summary['createdAt'] = datetime.now(timezone.utc).isoformat()
        summary['files'] = {name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in (('report.json', sanitized), ('sbom.cdx.json', sbom))}
        output.mkdir(mode=0o700)
        for name, path in (('report.json', sanitized), ('sbom.cdx.json', sbom)):
            (output/name).write_bytes(path.read_bytes())
        # Last file is the evidence completion marker; policyPassed may be false.
        (output/'manifest.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trivy', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--source', choices=['remote', 'docker'], required=True)
    parser.add_argument('--scope', choices=['base', 'application'], required=True)
    parser.add_argument('--commit')
    parser.add_argument('--role', choices=['backend', 'frontend', 'sandbox'])
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--cache-dir', required=True)
    args = parser.parse_args(argv)
    try:
        summary = run_scan(trivy=args.trivy, target=args.image, source=args.source,
            scope=args.scope, commit=args.commit, output=args.output_dir, cache=args.cache_dir, role=args.role)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print('Image scan failed: ' + (str(exc) if isinstance(exc, ScanError) else type(exc).__name__))
        return 2
    print(json.dumps(summary))
    return 0 if summary['policyPassed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
