"""Public practice submissions cannot supply judge resource limits."""

import pytest

from app.models.schemas import SubmissionRequest


def test_practice_submission_accepts_only_code_and_language():
    parsed = SubmissionRequest.model_validate({'code': 'print(1)', 'language': 'python'})
    assert parsed.model_dump() == {'code': 'print(1)', 'language': 'python'}


@pytest.mark.parametrize('field,value', [
    ('cpuMs', 1), ('wallMs', 1), ('memoryBytes', 1),
    ('pids', 1000), ('judgePolicy', {'reviewStatus': 'verified'}),
])
def test_practice_submission_rejects_client_resource_overrides(field, value):
    with pytest.raises(ValueError, match='Extra inputs are not permitted'):
        SubmissionRequest.model_validate({
            'code': 'print(1)', 'language': 'python', field: value,
        })
