from typing import List, Literal, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from datetime import datetime


CompilerLanguage = Literal["bpp", "python", "c", "cpp", "java", "javascript"]
CompilerTarget = Literal["ast", "ssa", "ir", "asm", "all"]


class CodeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    language: CompilerLanguage
    source_code: str = Field(validation_alias=AliasChoices("source_code", "code"))
    stdin: str | None = None
    optimize: bool = False


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
    code: str
    language: CompilerLanguage = "bpp"
    options: CompileOptions = Field(default_factory=CompileOptions)


class CompileDiagnostic(BaseModel):
    line: int = 1
    column: int = 1
    message: str
    severity: Literal["error", "warning", "info"]
    code: str | None = None


class CompileMetadata(BaseModel):
    node_count: int | None = None
    optimization_level: int | None = None


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
    class Config:
        from_attributes = True


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True
    )


class LeaderboardRead(CamelModel):
    rank: int
    username: str
    total_score: int
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
    ]
    tags: List[Literal["io", "control", "func"]]
    description: str
    test_cases: List[TestCase] = Field(
        default_factory=list,
        validation_alias=AliasChoices("test_cases", "testCases", "sample_test_cases", "sampleTestCases"),
    )
    hidden_test_cases: List[TestCase] = Field(
        default_factory=list,
        validation_alias=AliasChoices("hidden_test_cases", "hiddenTestCases"),
    )


class ProblemCreate(ProblemBase):
    pass


class ProblemRead(CamelModel):
    id: str
    creator_id: str
    title: str
    difficulty: str
    tags: List[str]
    description: str
    test_cases: List[TestCase]
    hidden_test_cases: List[TestCase] = Field(default_factory=list)
    created_at: datetime

class ProblemDetail(ProblemBase):
    id: str
    created_at: datetime

class UserCreate(CamelModel):
    username: str = Field(min_length=3, max_length=50)
    nickname: Optional[str] = Field(default=None, min_length=2, max_length=30)
    password: str = Field(min_length=8)

class UserLogin(CamelModel):
    username: str
    password: str

class UserRead(CamelModel):
    id: str
    username: str
    nickname: Optional[str] = None
    total_score: int
    avatar_url: Optional[str] = None

class Token(CamelModel):
    access_token: str
    token_type: str

class SubmissionRequest(CamelModel):
    code: str
    language: CompilerLanguage

class TestCaseResult(CamelModel):
    case_number: int
    phase: Literal["sample", "hidden"]
    is_visible: bool = True
    status: Literal["Correct", "Wrong", "Error"]
    input: str
    expected: str
    actual: str

class SubmissionResponse(CamelModel):
    status: str
    total_cases: int
    passed_cases: int
    sample_total_cases: int
    sample_passed_cases: int
    hidden_total_cases: int
    hidden_passed_cases: int
    hidden_completed: bool
    total_score: int
    details: List[TestCaseResult]

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


class CommunityPostRead(CamelModel):
    id: str
    problem_id: str
    author: str
    avatar_url: Optional[str] = None
    content: str
    created_at: datetime


class CommunityPostCountsRequest(CamelModel):
    problem_ids: List[str]
