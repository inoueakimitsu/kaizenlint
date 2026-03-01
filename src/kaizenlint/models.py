from typing import Annotated, Literal

from pydantic import BaseModel, Field


class LlmCheckerConfig(BaseModel):
    type: Literal["llm"] = "llm"
    profile: str = "light"


class RegexCheckerConfig(BaseModel):
    type: Literal["regex"] = "regex"


CheckerConfig = LlmCheckerConfig | RegexCheckerConfig


DEFAULT_CHECKER_CONFIG = LlmCheckerConfig()


class LintRule(BaseModel):
    title: str
    description: str
    checker: Annotated[CheckerConfig, Field(discriminator="type")]


class LintSource(BaseModel):
    content: str


class LintSourceName(BaseModel):
    name: str | None = None


class LintViolationMessage(BaseModel):
    text: str


class LintViolation(BaseModel):
    rule: LintRule
    message: LintViolationMessage


class CheckTask(BaseModel):
    source: LintSource
    source_name: LintSourceName
    rule: LintRule


class _LlmJudgement(BaseModel):
    violated: bool
    message: str


class LlmEndpoint(BaseModel):
    base_url: str | None = None
    max_concurrency: int = 5


class LlmProfile(BaseModel):
    model: str
    temperature: float | None = None
    endpoint: str = "default"


class LlmConfig(BaseModel):
    endpoints: dict[str, LlmEndpoint] = Field(default_factory=dict)
    profiles: dict[str, LlmProfile]


class ExecutorConfig(BaseModel):
    model_config = {"populate_by_name": True}

    type: str = "async"
    default_concurrency: int = Field(default=5, alias="default-concurrency")


class KaizenlintConfig(BaseModel):
    model_config = {"populate_by_name": True}

    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
    llm: LlmConfig
    include: list[str] = Field(default_factory=lambda: ["*.py", "*.md", "*.txt"])
    exclude: list[str] = Field(
        default_factory=lambda: [
            ".git", ".venv", "__pycache__", "node_modules", ".kaizenlint"
        ]
    )
    extend_exclude: list[str] = Field(default_factory=list, alias="extend-exclude")
    force_exclude: bool = Field(default=False, alias="force-exclude")
    respect_gitignore: bool = Field(default=True, alias="respect-gitignore")
    rules: list[str] = Field(default_factory=lambda: ["rules/**/*.md"])
