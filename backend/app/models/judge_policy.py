"""Versioned judge limits. No inferred universal language multipliers.

Limits are absolute after review; candidate formulas belong to authoring only.
This module deliberately does not import application/database configuration.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Language = Literal['bpp', 'c', 'cpp', 'python', 'java', 'javascript']
SUPPORTED_LANGUAGES = frozenset(('bpp', 'c', 'cpp', 'python', 'java', 'javascript'))
Digest = Annotated[str, Field(pattern=r'^sha256:[0-9a-f]{64}$')]
Identifier = Annotated[str, Field(min_length=1, max_length=80, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$')]


def _camel(value: str) -> str:
    head, *tail = value.split('_')
    return head + ''.join(word.title() for word in tail)


class PolicyModel(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True, alias_generator=_camel)


class StageLimits(PolicyModel):
    # Integer bytes/ms avoids MB/MiB ambiguity, floats, booleans and truncation.
    cpu_ms: int = Field(strict=True, ge=1, le=300_000)
    wall_ms: int = Field(strict=True, ge=1, le=600_000)
    memory_bytes: int = Field(strict=True, ge=1_048_576, le=8 * 1024**3)
    output_bytes: int = Field(strict=True, ge=1, le=16 * 1024**2)
    pids: int = Field(strict=True, ge=1, le=256)
    tmp_bytes: int = Field(strict=True, ge=0, le=8 * 1024**3)

    @model_validator(mode='after')
    def validate_memory_scope(self):
        if self.tmp_bytes > self.memory_bytes:
            raise ValueError('Temporary storage must fit inside the total cgroup memory budget')
        return self


class RuntimeLimits(PolicyModel):
    runtime_id: Identifier
    runtime_version: str = Field(min_length=1, max_length=160)
    image_digest: Digest
    worker_class: Identifier
    # Compiler options are selected by a trusted runtime registry, never shell
    # fragments supplied by participants or arbitrary administrator arguments.
    toolchain_profile: Identifier
    # Drafts can be authored before selecting an implementation. Publication
    # and measured execution require this exact hash; upgrades cannot silently
    # reinterpret a frozen receipt with a different supervisor.
    launcher_digest: Digest | None = None
    compile: StageLimits
    run: StageLimits


class MeasurementEvidence(PolicyModel):
    report_hash: Digest
    resource_fingerprint: Digest
    host_class: Identifier
    repetitions: int = Field(strict=True, ge=10, le=100_000)
    case_count: int = Field(strict=True, ge=1, le=200)
    max_cpu_ms: int = Field(strict=True, ge=0)
    max_wall_ms: int = Field(strict=True, ge=0)
    peak_memory_bytes: int = Field(strict=True, ge=0)
    safety_margin_reason: str = Field(min_length=1, max_length=2000)


class JudgePolicy(PolicyModel):
    schema_version: Literal[1] = 1
    policy_id: Identifier
    revision: int = Field(strict=True, ge=1)
    review_status: Literal['draft', 'verified'] = 'draft'
    test_suite_hash: Digest
    profiles: dict[Language, RuntimeLimits] = Field(min_length=1, max_length=6)
    evidence: dict[Language, MeasurementEvidence] = Field(default_factory=dict, max_length=6)
    preparation_cleanup_ms: int = Field(strict=True, ge=1000, le=120_000)

    @field_validator('schema_version', mode='before')
    @classmethod
    def strict_schema_version(cls, value):
        if type(value) is not int:
            raise ValueError('Schema version must be an integer, not a coerced value')
        return value

    @model_validator(mode='after')
    def validate_review(self):
        if set(self.evidence) - set(self.profiles):
            raise ValueError('Evidence must belong to a supported runtime profile')
        if self.review_status == 'verified' and set(self.evidence) != set(self.profiles):
            raise ValueError('Every supported language requires measurement evidence')
        for language, evidence in self.evidence.items():
            limits = self.profiles[language]
            if evidence.host_class != limits.worker_class:
                raise ValueError('Measurements must use the selected worker class')
            if (evidence.max_cpu_ms >= limits.run.cpu_ms
                    or evidence.max_wall_ms >= limits.run.wall_ms
                    or evidence.peak_memory_bytes >= limits.run.memory_bytes):
                raise ValueError('Reference solutions require positive headroom below each limit')
        return self
