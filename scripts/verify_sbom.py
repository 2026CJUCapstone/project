#!/usr/bin/env python3
"""Check a CycloneDX dependency inventory against the exact source lockfile.

This is a lock-inventory contract, not a complete CycloneDX schema validator,
installed-image inventory, vulnerability scanner or signed attestation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


class SBOMError(ValueError):
    pass


def normalized(name, ecosystem):
    if not isinstance(name, str) or not name:
        raise SBOMError('Missing dependency name')
    return re.sub(r'[-_.]+', '-', name).lower() if ecosystem == 'pypi' else name


def expected_packages(raw, ecosystem):
    expected = set()
    if ecosystem == 'npm':
        lock = json.loads(raw)
        if lock.get('lockfileVersion') != 3 or not isinstance(lock.get('packages'), dict):
            raise SBOMError('An npm v3 lockfile is required')
        for path, package in lock['packages'].items():
            if path == '':
                continue
            if not isinstance(package, dict) or package.get('link') or 'node_modules/' not in path:
                raise SBOMError('Unsupported npm lock entry')
            name = package.get('name') or path.rsplit('node_modules/', 1)[-1]
            version = package.get('version')
            if not isinstance(version, str) or not version:
                raise SBOMError('Missing locked dependency version')
            expected.add((normalized(name, ecosystem), version))
    elif ecosystem == 'pypi':
        for line in raw.decode('utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if re.fullmatch(r'--hash=sha256:[0-9a-f]{64}\s*\\?', line):
                continue
            match = re.fullmatch(r'([A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?==([^\s;]+)\s*\\?', line)
            if not match:
                raise SBOMError('Unsupported or unpinned Python requirement')
            expected.add((normalized(match[1], ecosystem), match[2]))
    else:
        raise SBOMError('Unsupported dependency ecosystem')
    if not expected:
        raise SBOMError('Empty dependency lock inventory')
    return expected


def verify(lock_bytes, sbom_bytes, ecosystem, commit):
    if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise SBOMError('An exact source commit is required')
    expected = expected_packages(lock_bytes, ecosystem)
    bom = json.loads(sbom_bytes)
    if not isinstance(bom, dict) or bom.get('bomFormat') != 'CycloneDX':
        raise SBOMError('A CycloneDX JSON inventory is required')
    if not isinstance(bom.get('specVersion'), str) or not re.fullmatch(r'1\.\d+', bom['specVersion']):
        raise SBOMError('Missing CycloneDX specification version')
    components = bom.get('components')
    if not isinstance(components, list) or not components:
        raise SBOMError('Empty dependency SBOM')
    observed, refs = set(), set()
    for component in components:
        if not isinstance(component, dict) or component.get('components'):
            raise SBOMError('Unsupported dependency component')
        name, version, ref = component.get('name'), component.get('version'), component.get('bom-ref')
        if component.get('type') != 'library' or not isinstance(version, str) or not version:
            raise SBOMError('Invalid dependency component version or type')
        if not isinstance(ref, str) or not ref or ref in refs:
            raise SBOMError('Missing or duplicate component reference')
        refs.add(ref)
        observed.add((normalized(name, ecosystem), version))
    if observed != expected:
        raise SBOMError('SBOM dependencies do not match the source lockfile')
    metadata = bom.get('metadata', {})
    root = metadata.get('component', {}) if isinstance(metadata, dict) else {}
    if isinstance(root, dict) and root.get('bom-ref'):
        if root['bom-ref'] in refs:
            raise SBOMError('Root and dependency references collide')
        refs.add(root['bom-ref'])
    dependencies = bom.get('dependencies', [])
    if not isinstance(dependencies, list):
        raise SBOMError('Invalid dependency graph')
    graph_refs = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            raise SBOMError('Invalid dependency graph entry')
        ref, children = dependency.get('ref'), dependency.get('dependsOn', [])
        if not isinstance(ref, str) or ref not in refs or ref in graph_refs or not isinstance(children, list):
            raise SBOMError('Invalid dependency graph reference')
        if any(not isinstance(child, str) or child not in refs for child in children):
            raise SBOMError('Unresolved dependency graph reference')
        graph_refs.add(ref)
    return {'schemaVersion': 1, 'sourceCommit': commit, 'ecosystem': ecosystem,
        'inventoryScope': 'source-lockfile-not-installed-image',
        'lockfileSha256': hashlib.sha256(lock_bytes).hexdigest(),
        'sbomSha256': hashlib.sha256(sbom_bytes).hexdigest(),
        'componentCount': len(components), 'uniquePackageVersions': len(expected),
        'cycloneDxVersion': bom['specVersion']}


def read_bounded(path):
    if path == '-':
        raw = sys.stdin.buffer.read(32 * 1024 * 1024 + 1)
    else:
        with Path(path).open('rb') as stream:
            raw = stream.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise SBOMError('Dependency inventory exceeds the input budget')
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ecosystem', required=True, choices=['npm', 'pypi'])
    parser.add_argument('--lockfile', required=True)
    parser.add_argument('--sbom', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    try:
        manifest = verify(read_bounded(args.lockfile), read_bounded(args.sbom), args.ecosystem, args.commit)
        # A stale report must not be silently replaced by a later invocation.
        with Path(args.manifest).open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, indent=2, sort_keys=True)
            stream.write('\n')
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        print('SBOM verification failed; no verified manifest was produced', file=sys.stderr)
        return 1
    print('Verified '+args.ecosystem+' lock inventory: '+str(manifest['uniquePackageVersions'])+' package versions')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
