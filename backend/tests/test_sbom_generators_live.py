"""Opt-in real source-lock generators; does not install application packages.

Requires network for the pinned npm tool and pip-audit advisory service.
SBOM_AUDIT_PYTHON must name an isolated Python with pip-audit 2.10.1 installed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.test_sbom_inventory import COMMIT, sbom


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.getenv('RUN_SBOM_INTEGRATION') != '1',
    reason='explicit source-lock generator/advisory integration opt-in required')


@pytest.mark.parametrize('ecosystem', ['npm', 'pypi'])
def test_actual_generator_matches_current_lock_and_detects_tampering(ecosystem, tmp_path):
    output = tmp_path / (ecosystem + '.cdx.json')
    if ecosystem == 'npm':
        executable = os.getenv('SBOM_NPX') or shutil.which('npx')
        assert executable, 'npx is required when integration is opted in'
        command = [executable, '--yes', '--package', 'npm@11.19.1', '--', 'npm',
            'sbom', '--package-lock-only', '--sbom-format', 'cyclonedx', '--sbom-type', 'application']
        lock = ROOT / 'frontend/package-lock.json'
        with output.open('wb') as stream:
            result = subprocess.run(command, cwd=ROOT / 'frontend', stdout=stream,
                stderr=subprocess.PIPE, timeout=180, check=False)
    else:
        executable = os.getenv('SBOM_AUDIT_PYTHON')
        assert executable, 'a dedicated pip-audit Python is required when opted in'
        version = subprocess.run([executable, '-m', 'pip_audit', '--version'],
            capture_output=True, timeout=20, check=False)
        assert version.returncode == 0 and version.stdout.strip() == b'pip-audit 2.10.1'
        lock = ROOT / 'backend/requirements.lock'
        command = [executable, '-m', 'pip_audit', '--requirement', str(lock),
            '--disable-pip', '--strict', '--format', 'cyclonedx-json',
            '--output', str(output), '--timeout', '10']
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=180, check=False)
    # A scanner finding/outage is a failing test, never a fabricated passing fixture.
    assert result.returncode == 0, 'Actual generator/audit failed: ' + result.stderr.decode(errors='replace')[:2000]
    lock_bytes, bom_bytes = lock.read_bytes(), sbom.read_bounded(output)
    manifest = sbom.verify(lock_bytes, bom_bytes, ecosystem, COMMIT)
    assert manifest['uniquePackageVersions'] == len(sbom.expected_packages(lock_bytes, ecosystem))
    assert manifest['inventoryScope'] == 'source-lockfile-not-installed-image'
    # This is deliberately a fixture SHA, not an attestation of the dirty checkout.
    assert manifest['sourceCommit'] == COMMIT
    bom = json.loads(bom_bytes)
    bom['components'][0]['version'] = 'wrong-version'
    with pytest.raises(sbom.SBOMError, match='do not match'):
        sbom.verify(lock_bytes, json.dumps(bom).encode(), ecosystem, COMMIT)
