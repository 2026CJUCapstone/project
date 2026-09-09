from datetime import datetime
from pydantic import Field, field_validator, model_validator
from app.models.schemas import CamelModel, CompilerLanguage, ProblemCreate


class ContestProblemWrite(CamelModel):
    problem_id: str | None = None
    new_problem: ProblemCreate | None = None
    points: int = Field(ge=1, le=100000)

    @model_validator(mode="after")
    def validate_source(self):
        if not self.problem_id and self.new_problem is None:
            raise ValueError("기존 문제 또는 신규 문제를 지정하세요.")
        return self


class ContestWrite(CamelModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=20000)
    starts_at: datetime
    ends_at: datetime
    published: bool = False
    problems: list[ContestProblemWrite] = Field(default_factory=list, max_length=26)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("시간대가 포함된 시각이 필요합니다.")
        return value

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("종료 시각은 시작 시각보다 늦어야 합니다.")
        if not self.title.strip():
            raise ValueError("대회 제목이 필요합니다.")
        if self.published and not self.problems:
            raise ValueError("대회 공개에는 문제가 한 개 이상 필요합니다.")
        return self


class ContestSubmit(CamelModel):
    code: str = Field(min_length=1)
    language: CompilerLanguage
    request_id: str = Field(min_length=1, max_length=80)
