from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


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
