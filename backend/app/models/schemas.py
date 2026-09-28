from typing import Dict, List, Literal, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel
from datetime import datetime
import re
from app.models.judge_policy import JudgePolicy
from app.models.judge_test_manifest import StoredTestCase,is_reference_case,canonical_case,canonical_suite


CompilerLanguage = Literal["bpp", "python", "c", "cpp", "java", "javascript"]
CompilerTarget = Literal["ast", "ssa", "ir", "asm", "all"]
CompileQueueVerdict = Literal[
    "pending",
    "running",
    "compile_success",
    "compile_error",
    "accepted",
    "wrong_answer",
    "finished",
    "runtime_error",
    "time_limit_exceeded",
    "memory_limit_exceeded",
    "output_limit_exceeded",
    "process_limit_exceeded",
    "compile_resource_error",
    "system_error",
    "canceled",
]


class CodeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    language: CompilerLanguage
    source_code: str = Field(validation_alias=AliasChoices("source_code", "code"))
    stdin: str | None = None
    optimize: bool = False
    problem_id: str | None = Field(
        default=None,
        max_length=128,
        validation_alias=AliasChoices("problem_id", "problemId"),
    )


class CodeResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    execution_time: float


class CompileOptions(BaseModel):
    optimize: bool = False
    target: CompilerTarget = "all"
    debug: bool = False


class CompileRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str
    language: CompilerLanguage = "bpp"
    options: CompileOptions = Field(default_factory=CompileOptions)
    problem_id: str | None = Field(
        default=None,
        max_length=128,
        validation_alias=AliasChoices("problem_id", "problemId"),
    )


class CompileDiagnostic(BaseModel):
    line: int = 1
    column: int = 1
    message: str
    severity: Literal["error", "warning", "info"]
    code: str | None = None


class CompileMetadata(BaseModel):
    node_count: int | None = None
    optimization_level: int | None = None
    source_range_semantics: dict | None = None


class CompileResponse(BaseModel):
    success: bool
    ast: dict | None = None
    ssa: dict | None = None
    ir: dict | None = None
    asm: dict | None = None
    errors: list[CompileDiagnostic] = Field(default_factory=list)
    warnings: list[CompileDiagnostic] = Field(default_factory=list)
    execution_time: float
    metadata: CompileMetadata | None = None


class ChallengeBase(BaseModel):
    title: str
    description: str
    difficulty: str
    tags: List[str]
    points: int = 100


class ChallengeCreate(ChallengeBase):
    pass


class ChallengeRead(ChallengeBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True
    )


class CompileQueueJobRead(CamelModel):
    id: str
    kind: Literal["compile", "run", "grading"]
    status: Literal["queued", "running", "completed", "failed", "canceled"]
    verdict: CompileQueueVerdict
    language: CompilerLanguage
    username: Optional[str] = None
    user_id: Optional[str] = None
    problem_id: Optional[str] = None
    problem_title: Optional[str] = None
    target: Optional[str] = None
    source_size_bytes: Optional[int] = None
    source: Literal['ide', 'practice', 'contest'] = 'ide'
    contest_id: Optional[str] = None
    contest_title: Optional[str] = None
    contest_problem_id: Optional[str] = None
    queued_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    wait_ms: Optional[float] = None
    run_ms: Optional[float] = None
    position: Optional[int] = None
    error: Optional[str] = None
    verdict_detail: Optional[str] = None


class CompileQueueGroupRead(CamelModel):
    key: str
    label: str
    problem_id: Optional[str] = None
    problem_title: Optional[str] = None
    contest_id: Optional[str] = None
    contest_title: Optional[str] = None
    contest_problem_id: Optional[str] = None
    username: Optional[str] = None
    user_id: Optional[str] = None
    total: int
    queued: int
    running: int
    completed: int
    failed: int
    canceled: int
    verdicts: Dict[str, int] = Field(default_factory=dict)
    last_queued_at: Optional[datetime] = None


class CompileHistoryOption(CamelModel):
    id: str
    title: str
    contest_id: Optional[str] = None


class CompileQueueResponse(CamelModel):
    jobs: List[CompileQueueJobRead]
    total: int
    filtered_total: int
    queued: int
    running: int
    problem_groups: List[CompileQueueGroupRead] = Field(default_factory=list)
    user_groups: List[CompileQueueGroupRead] = Field(default_factory=list)
    contest_options: List[CompileHistoryOption] = Field(default_factory=list)
    problem_options: List[CompileHistoryOption] = Field(default_factory=list)
    option_limit: int = 200
    options_truncated: bool = False
    detail_scope: Literal["aggregate", "mine", "admin"] = "aggregate"


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if len(normalized) > 254 or not EMAIL_PATTERN.match(normalized):
        raise ValueError("올바른 이메일 주소를 입력하세요.")
    return normalized


class LeaderboardRead(CamelModel):
    rank: int
    username: str
    total_score: int
    rating: int
    tier: str
    solved_count: int
    avatar_url: Optional[str] = None


class LeaderboardScoreCreate(CamelModel):
    username: str = Field(min_length=1, max_length=64)
    points: int = Field(gt=0, le=10000)
    challenge_id: str = Field(min_length=1, max_length=128)
    avatar_url: Optional[str] = None


class LeaderboardScoreRead(LeaderboardRead):
    challenge_id: str
    awarded_points: int
    already_solved: bool


class TagProficiencyRead(CamelModel):
    tag: str
    solved_count: int
    difficulty_score: int
    max_difficulty: Optional[str] = None
    max_difficulty_value: int = 0
    proficiency: int


class TestCase(CamelModel):
    input: str
    expected_output: str


class ProblemBase(CamelModel):
    title: str
    difficulty: Literal[
        "iron5", "iron4", "iron3", "iron2", "iron1",
        "bronze5", "bronze4", "bronze3", "bronze2", "bronze1",
        "silver5", "silver4", "silver3", "silver2", "silver1",
        "gold5", "gold4", "gold3", "gold2", "gold1",
        "platinum5", "platinum4", "platinum3", "platinum2", "platinum1",
        "diamond5", "diamond4", "diamond3", "diamond2", "diamond1",
        "ruby5", "ruby4", "ruby3", "ruby2", "ruby1",
    ]
    tags: List[str] = Field(default_factory=list, max_length=12)
    description: str
    points: int = Field(default=100, ge=0, le=10000)
    test_cases: List[TestCase] = Field(
        default_factory=list,
        validation_alias=AliasChoices("test_cases", "testCases", "sample_test_cases", "sampleTestCases"),
    )
    hidden_test_cases: List[TestCase | StoredTestCase] = Field(
        default_factory=list,
        validation_alias=AliasChoices("hidden_test_cases", "hiddenTestCases"),
    )

    @field_validator('test_cases','hidden_test_cases',mode='before')
    @classmethod
    def preserve_test_references(cls,value,info):
        # Prevent a permissive inline model from silently discarding reference
        # fields in an ambiguous union payload.
        if isinstance(value,list):
            for case in value:
                raw=case.model_dump() if hasattr(case,'model_dump') else case
                if is_reference_case(raw):
                    canonical_case(raw,allow_reference=info.field_name=='hidden_test_cases')
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: List[str]) -> List[str]:
        normalized: list[str] = []
        for tag in value:
            text = tag.strip().lower()
            if not text:
                continue
            if len(text) > 32 or not re.match(r"^[a-z0-9_-]+$", text):
                raise ValueError("태그는 영문, 숫자, -, _ 조합으로 32자 이하만 사용할 수 있습니다.")
            if text not in normalized:
                normalized.append(text)
        return normalized


class ProblemCreate(ProblemBase):
    judge_policy: JudgePolicy | None = None

    @model_validator(mode="after")
    def validate_test_suite_budget(self):
        # Unpublished drafts may have no tests yet. Every nonempty suite must
        # obey the same count and decoded-byte bounds as stored test manifests.
        if self.test_cases or self.hidden_test_cases:
            canonical_suite(
                [case.model_dump(by_alias=True) for case in self.test_cases],
                [case.model_dump(by_alias=True) for case in self.hidden_test_cases],
            )
        return self


class ProblemRead(CamelModel):
    id: str
    creator_id: Optional[str] = None
    title: str
    difficulty: str
    tags: List[str]
    description: str
    points: int = 100
    test_cases: List[TestCase]
    hidden_test_cases: List[TestCase | StoredTestCase] = Field(default_factory=list)
    created_at: datetime
    solved: bool = False
    attempted: bool = False
    last_submission_status: Optional[str] = None
    last_submission_verdict: Optional[CompileQueueVerdict] = None
    last_submitted_at: Optional[datetime] = None
    best_awarded_points: int = 0
    judge_limits: dict | None = None
    judge_policy_legacy: bool = False
    judge_policy_compatibility: bool = False
    judge_policy: dict | None = None
    publication_status: Literal["legacy", "draft", "published"] = "legacy"

class ProblemDetail(ProblemBase):
    id: str
    created_at: datetime

class UserCreate(CamelModel):
    username: str = Field(min_length=3, max_length=50)
    email: str = Field(min_length=3, max_length=254)
    nickname: Optional[str] = Field(default=None, min_length=2, max_length=30)
    password: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if normalized is None:
            raise ValueError("이메일을 입력하세요.")
        return normalized

class UserLogin(CamelModel):
    username: str
    password: str

class UserRead(CamelModel):
    id: str
    username: str
    email: Optional[str] = None
    nickname: Optional[str] = None
    total_score: int
    rating: int = 0
    tier: str = "Unrated"
    solved_count: int = 0
    difficulty_score: int = 0
    solved_bonus: int = 0
    top_difficulties: List[str] = Field(default_factory=list)
    tag_proficiencies: List[TagProficiencyRead] = Field(default_factory=list)
    avatar_url: Optional[str] = None
    role: str = "user"
    public_profile_enabled: bool = True

class UserProfileUpdate(CamelModel):
    email: Optional[str] = Field(default=None, max_length=254)
    nickname: Optional[str] = Field(default=None, min_length=2, max_length=30)
    avatar_url: Optional[str] = Field(default=None, max_length=500)

    @field_validator("email")
    @classmethod
    def validate_optional_email(cls, value: Optional[str]) -> Optional[str]:
        return normalize_email(value)

class AdminUserRead(UserRead):
    created_at: Optional[datetime] = None

class AdminUserUpdate(CamelModel):
    role: Optional[Literal["user", "admin"]] = None
    email: Optional[str] = Field(default=None, max_length=254)
    nickname: Optional[str] = Field(default=None, min_length=2, max_length=30)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    public_profile_enabled: Optional[bool] = None

    @field_validator("email")
    @classmethod
    def validate_admin_email(cls, value: Optional[str]) -> Optional[str]:
        return normalize_email(value)

class Token(CamelModel):
    access_token: str
    token_type: str


class PasswordResetRequest(CamelModel):
    username_or_email: str = Field(
        min_length=3,
        max_length=254,
        validation_alias=AliasChoices("username_or_email", "usernameOrEmail", "username", "email"),
    )


class PasswordResetConfirm(CamelModel):
    token: str = Field(min_length=32, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class PasswordResetResponse(CamelModel):
    message: str
    debug_reset_token: Optional[str] = None

class SubmissionRequest(CamelModel):
    model_config = ConfigDict(extra='forbid')

    code: str
    language: CompilerLanguage

class PhaseResourceUsage(CamelModel):
    cpu_ms: float
    wall_ms: float
    peak_memory_bytes: int


class RunResourceUsage(PhaseResourceUsage):
    max_cpu_ms: float
    max_wall_ms: float


class JudgeResourceUsage(CamelModel):
    version: Literal[1]
    measurement: Literal['cgroup-v2-whole-phase']
    policy_id: str
    policy_revision: int
    compile: PhaseResourceUsage
    run: RunResourceUsage | None = None


class TestCaseResult(CamelModel):
    case_number: int
    phase: Literal["sample", "grading"]
    is_visible: bool = True
    status: Literal["Correct", "Wrong", "Error"]
    verdict: CompileQueueVerdict
    input: str
    expected: str
    actual: str

class SubmissionResponse(CamelModel):
    resource_usage: JudgeResourceUsage | None = None
    status: str
    verdict: CompileQueueVerdict
    total_cases: int
    passed_cases: int
    sample_total_cases: int
    sample_passed_cases: int
    grading_completed: bool
    grading_passed: bool
    total_score: int
    details: List[TestCaseResult]
    message: str

class CommentBase(CamelModel):
    content: str = Field(min_length=1, max_length=1000)

class CommentCreate(CommentBase):
    pass

class CommentRead(CommentBase):
    id: str
    problem_id: str
    user_id: str
    created_at: datetime


class CommunityPostCreate(CamelModel):
    problem_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=1000)


class CommunityPostUpdate(CamelModel):
    content: str = Field(min_length=1, max_length=1000)


class CommunityPostRead(CamelModel):
    id: str
    problem_id: str
    user_id: Optional[str] = None
    author: str
    avatar_url: Optional[str] = None
    content: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    can_delete: bool = False
    can_edit: bool = False


class CommunityPostCountsRequest(CamelModel):
    problem_ids: List[str]


class CodeProjectBase(CamelModel):
    code: str
    language: CompilerLanguage = "bpp"
    title: str = Field(default="main", min_length=1, max_length=120)


class CodeProjectUpsert(CodeProjectBase):
    expected_revision: str | None = Field(default=None, min_length=1, max_length=64)


class CodeProjectRead(CodeProjectBase):
    id: str
    revision: str
    scope: str
    created_at: datetime
    updated_at: datetime


class SubmissionRead(CamelModel):
    id: str
    problem_id: str
    problem_title: Optional[str] = None
    user_id: Optional[str] = None
    username: Optional[str] = None
    language: CompilerLanguage
    status: str
    verdict: CompileQueueVerdict
    sample_total_cases: int
    sample_passed_cases: int
    grading_completed: bool
    grading_passed: bool
    awarded_points: int
    resource_usage: JudgeResourceUsage | None = None
    created_at: datetime


class SubmissionListResponse(CamelModel):
    submissions: List[SubmissionRead]
    total: int
    filtered_total: int


class AdminUsersResponse(CamelModel):
    users: List[AdminUserRead]
    total: int
    filtered_total: int
