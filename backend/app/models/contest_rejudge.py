"""Bounded correction proposals with no client-provided scores or verdicts."""
from typing import Literal
from pydantic import Field, field_validator, model_validator
from app.models.judge_policy import PolicyModel, JudgePolicy, Digest, Identifier
from app.models.schemas import TestCase
from app.models.judge_test_manifest import StoredTestCase, canonical_suite
from app.models.problem_authoring import AuthoringMetadata, ReviewWrite


class RejudgeCreate(PolicyModel):
    request_id: Identifier
    contest_problem_id: str = Field(min_length=1, max_length=80)
    expected_snapshot_hash: Digest
    reason: str = Field(min_length=10, max_length=2000)
    sample: list[TestCase] = Field(max_length=200)
    hidden: list[TestCase | StoredTestCase] = Field(max_length=200)
    judge_policy: JudgePolicy
    authoring: AuthoringMetadata | None = None

    @field_validator('authoring', mode='before')
    @classmethod
    def no_metadata_removal(cls, value):
        if value is None:
            raise ValueError('검수 근거를 지울 수 없습니다. 유지하려면 필드를 생략하세요.')
        return value

    @field_validator('reason')
    @classmethod
    def meaningful_reason(cls, value):
        if len(value.strip()) < 10:
            raise ValueError('변경 이유를 10자 이상 작성하세요.')
        return value.strip()

    @model_validator(mode='before')
    @classmethod
    def strict_cases(cls, value):
        if isinstance(value, dict):
            canonical_suite(value.get('sample', []), value.get('hidden', []))
        return value


class RejudgeDiscard(PolicyModel):
    expected_request_hash: Digest


class RejudgeReview(ReviewWrite):
    expected_request_hash: Digest


class RejudgeApply(RejudgeDiscard):
    expected_preview_hash: Digest
    expected_scoreboard_revision: int = Field(ge=0, strict=True)
    public_note: str = Field(min_length=10, max_length=1000)

    @field_validator('public_note')
    @classmethod
    def meaningful_note(cls, value):
        if len(value.strip()) < 10:
            raise ValueError('참가자에게 공개할 정정 사유를 10자 이상 작성하세요.')
        return value.strip()


class LegacySolveResolutionWrite(PolicyModel):
    request_id: Identifier
    expected_request_hash: Digest
    user_id: str = Field(min_length=1, max_length=80)
    expected_legacy_fingerprint: Digest
    decision: Literal['retain_unattributed', 'link_verified_receipt']
    source_kind: Literal['practice', 'contest'] | None = None
    source_id: str | None = Field(default=None, min_length=1, max_length=80)
    note: str = Field(min_length=10, max_length=2000)

    @field_validator('note')
    @classmethod
    def meaningful_resolution_note(cls, value):
        if len(value.strip()) < 10:
            raise ValueError('검수 근거를 10자 이상 작성하세요.')
        return value.strip()

    @model_validator(mode='after')
    def source_matches_decision(self):
        linked = self.decision == 'link_verified_receipt'
        if linked != bool(self.source_kind and self.source_id):
            raise ValueError('검증 영수증 연결 결정에는 출처 종류와 ID가 모두 필요합니다.')
        return self
