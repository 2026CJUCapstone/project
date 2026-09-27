"""Administrator-only authoring facts; approvals are separate server events."""
from datetime import datetime
import json
from typing import Literal

from pydantic import ConfigDict, Field, HttpUrl, field_validator, model_validator
from app.models.schemas import CamelModel, ProblemCreate
from app.models.contest_schemas import ContestWrite
from app.models.judge_policy import Digest, Identifier
from app.models.judge_test_manifest import StoredTestCase,canonical_suite,has_stored_cases

# The normal API proxy accepts at most 512 KiB. Larger hidden inputs must be
# uploaded separately and referenced by digest, never embedded in this JSON.
MAX_PACKAGE_BYTES = 512 * 1024


def canonical_package_bytes(package):
    """The sole canonical camelCase JSON used for package sizing and transport.

    Do not replace this with ``model_dump_json()``: Pydantic defaults to the
    internal snake_case field names, while the importer and receipt protocol
    use aliases on the wire.  A near-limit package must be judged by the same
    bytes that the importer sends.
    """
    return json.dumps(package.model_dump(mode='json',by_alias=True),ensure_ascii=False,
                      sort_keys=True,separators=(',', ':'),allow_nan=False).encode('utf-8')


class StrictAuthoring(CamelModel):
    model_config=ConfigDict(extra='forbid')


class SourceReference(StrictAuthoring):
    url: HttpUrl
    title: str=Field(min_length=1,max_length=300)
    author: str=Field(default='',max_length=300)
    event: str=Field(default='',max_length=300)
    reuse_basis: Literal['pending','license','permission','original']='pending'
    reuse_evidence: str=Field(default='',max_length=4000)
    external_tier: str | None=Field(default=None,max_length=80)
    tier_checked_at: datetime | None=None

    @field_validator('tier_checked_at')
    @classmethod
    def require_zone(cls,value):
        if value is not None and value.tzinfo is None: raise ValueError('Tier check time needs a timezone')
        return value


class AssetReference(StrictAuthoring):
    role: Literal['reference','validator','generator','wrong_solution','proof','measurement']
    name: str=Field(min_length=1,max_length=240)
    digest: Digest
    language: Literal['bpp','c','cpp','python','java','javascript'] | None=None


class AuthoringMetadata(StrictAuthoring):
    sources: list[SourceReference]=Field(min_length=1,max_length=20)
    adaptation_notes: str=Field(min_length=1,max_length=10000)
    assets: list[AssetReference]=Field(default_factory=list,max_length=120)
    required_languages: list[Literal['bpp','c','cpp','python','java','javascript']]=Field(min_length=1,max_length=6)

    @field_validator('required_languages')
    @classmethod
    def unique_languages(cls,value):
        if len(set(value))!=len(value): raise ValueError('Duplicate required language')
        return value


class MetadataUpdate(StrictAuthoring):
    expected_fingerprint: Digest
    metadata: AuthoringMetadata


class ReviewWrite(StrictAuthoring):
    request_id: Identifier
    expected_fingerprint: Digest
    category: Literal['sources','statement','tests','resources']
    decision: Literal['approved','rejected']
    note: str=Field(min_length=1,max_length=4000)

    @field_validator('note')
    @classmethod
    def meaningful_note(cls,value):
        if not value.strip(): raise ValueError('Review note is required')
        return value


class PackagedProblem(ProblemCreate):
    model_config=ConfigDict(extra='forbid')


class PackageEntry(StrictAuthoring):
    key: Identifier
    points: int=Field(strict=True,ge=1,le=100000)
    problem: PackagedProblem
    metadata: AuthoringMetadata


class PrivateContestPackage(StrictAuthoring):
    schema_version: Literal[1]=1
    package_id: Identifier
    revision: int=Field(strict=True,ge=1)
    title: str=Field(min_length=1,max_length=120)
    description: str=Field(default='',max_length=20000)
    starts_at: datetime
    ends_at: datetime
    entries: list[PackageEntry]=Field(min_length=1,max_length=26)

    @field_validator('schema_version',mode='before')
    @classmethod
    def exact_version(cls,value):
        if type(value) is not int: raise ValueError('Integer schema version required')
        return value

    @model_validator(mode='after')
    def validate_package(self):
        self.contest_write()  # timezone and schedule validation, never public
        if len({e.key for e in self.entries})!=len(self.entries): raise ValueError('Duplicate package problem key')
        total=0
        for entry in self.entries:
            problem=entry.problem
            if not problem.title.strip() or len(problem.title)>200 or len(problem.description)>100000:
                raise ValueError('Invalid problem statement size')
            cases=problem.test_cases+problem.hidden_test_cases
            if not 1<=len(cases)<=200: raise ValueError('Package needs 1 to 200 tests per problem')
            samples=[c.model_dump() for c in problem.test_cases]
            hidden=[c.model_dump() for c in problem.hidden_test_cases]
            if has_stored_cases(samples,hidden): canonical_suite(samples,hidden)
            for case in cases:
                if isinstance(case,StoredTestCase): continue  # Separately uploaded/bounded data.
                size=len(case.input.encode('utf-8'))+len(case.expected_output.encode('utf-8'))
                if size>1_000_000: raise ValueError('Package case exceeds byte budget')
                total+=size
        if total>4_000_000 or len(canonical_package_bytes(self))>MAX_PACKAGE_BYTES:
            raise ValueError('Package exceeds aggregate byte budget')
        return self

    def contest_write(self):
        return ContestWrite(title=self.title,description=self.description,starts_at=self.starts_at,ends_at=self.ends_at,
            published=False,problems=[dict(points=e.points,new_problem=e.problem) for e in self.entries])
