"""Administrator input for resolving a contractless historical grading receipt."""
from typing import Literal

from pydantic import Field, field_validator

from app.models.judge_policy import Identifier, PolicyModel


class LegacyExecutionResolutionWrite(PolicyModel):
    request_id: Identifier
    expected_payload_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    judge_contract: dict
    verdict_schema_version: Literal['measured-v1']
    note: str = Field(min_length=10, max_length=2000)

    @field_validator('note')
    @classmethod
    def meaningful_note(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError('복구 근거를 10자 이상 입력해야 합니다.')
        return value
