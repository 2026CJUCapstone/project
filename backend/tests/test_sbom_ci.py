"""Workflow wiring gates; actual generators are tested separately."""
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('side,job,ecosystem,lock', [
    ('Backend', 'backend-tests', 'pypi', 'backend/requirements.lock'),
    ('Frontend', 'frontend-checks', 'npm', 'frontend/package-lock.json'),
])
def test_audit_failures_remain_blocking_but_valid_inventory_can_be_uploaded(side, job, ecosystem, lock):
    workflow = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8'))
    steps = workflow['jobs'][job]['steps']
    by_name = {step['name']: step for step in steps}
    audit = next(step for step in steps if step['name'].startswith('Audit ' + side + ' Dependencies'))
    validator = by_name['Validate ' + side + ' SBOM Against Locked Source']
    upload = by_name['Upload ' + side + ' Dependency SBOM']
    assert not audit.get('continue-on-error')
    assert '|| true' not in audit['run']
    assert not audit.get('if')
    assert validator['if'] == '${{ always() }}'
    assert not validator.get('continue-on-error')
    assert upload['if'] == "${{ always() && steps." + validator['id'] + ".outcome == 'success' }}"
    assert steps.index(audit) < steps.index(validator) < steps.index(upload)
    script = validator['run']
    assert 'set -euo pipefail' in script
    assert '--ecosystem ' + ecosystem in script
    assert '--lockfile ' + lock in script
    assert '--commit "$GITHUB_SHA"' in script
    assert 'test -s "$sbom"' in script
    assert 'test -s "$manifest"' in script
    label = side.lower()
    assert upload['with']['path'].splitlines() == [
        '${{ runner.temp }}/' + label + '-sbom.cdx.json',
        '${{ runner.temp }}/' + label + '-sbom.manifest.json']
    assert upload['with']['if-no-files-found'] == 'error'
    assert upload['with']['name'].endswith('${{ github.sha }}')
    if ecosystem == 'pypi':
        assert 'pip-audit==2.10.1' in audit['run']
        for argument in ('--disable-pip', '--strict', '--format cyclonedx-json', '--requirement ' + lock):
            assert argument in audit['run']
    else:
        assert audit['run'] == 'npm audit --audit-level=low'
        generator = by_name['Generate Frontend Lockfile SBOM']
        assert steps.index(generator) < steps.index(audit)
        assert 'npx --yes --package npm@11.19.1 -- npm sbom --package-lock-only' in generator['run']
        assert '--sbom-format cyclonedx' in generator['run']
        assert '--omit' not in generator['run']
        assert not generator.get('continue-on-error')
