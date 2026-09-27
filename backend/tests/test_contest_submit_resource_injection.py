import pytest
from pydantic import ValidationError

from app.models.contest_schemas import ContestSubmit


def _legitimate_payload() -> dict[str, str]:
    return {
        "code": "print('safe submission')",
        "language": "python",
        "requestId": "contest-submit-123",
    }


def test_contest_submit_exposes_no_resource_limit_input_fields():
    assert set(ContestSubmit.model_fields) == {"code", "language", "request_id"}


@pytest.mark.parametrize(
    ("field", "forged_value"),
    [
        ("cpuMs", 300_000),
        ("wallMs", 300_000),
        ("memoryBytes", 8 * 1024 * 1024 * 1024),
        ("pids", 4_096),
        ("judgePolicy", {"run": {"cpuMs": 300_000, "wallMs": 300_000}}),
    ],
)
def test_contest_submit_rejects_forged_resource_fields(field: str, forged_value: object):
    payload = _legitimate_payload() | {field: forged_value}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ContestSubmit.model_validate(payload)


def test_contest_submit_preserves_legitimate_code_language_and_request_id_alias():
    submission = ContestSubmit.model_validate(_legitimate_payload())

    assert submission.code == "print('safe submission')"
    assert submission.language == "python"
    assert submission.request_id == "contest-submit-123"
    assert submission.model_dump(by_alias=True) == _legitimate_payload()
