import fnmatch
from pathlib import Path
from typing import Annotated, Literal, Self, cast

from pydantic import BaseModel, Field, field_validator, model_validator


class LlmCheckerConfig(BaseModel):
    type: Literal["llm"] = "llm"
    profile: str = "light"


class RegexCheckerConfig(BaseModel):
    type: Literal["regex"] = "regex"


CheckerConfig = LlmCheckerConfig | RegexCheckerConfig


DEFAULT_CHECKER_CONFIG = LlmCheckerConfig()


class SuppressionEntry(BaseModel):
    rule: str
    messages: list[str] | None = Field(default=None, min_length=1)


class LintRule(BaseModel):
    title: str
    description: str
    checker: Annotated[CheckerConfig, Field(discriminator="type")]
    source_path: str = ""
    applies_to: list[str] = Field(default_factory=list)

    @field_validator("applies_to", mode="before")
    @classmethod
    def _coerce_applies_to(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            if not all(isinstance(item, str) for item in v):
                raise ValueError(
                    f"applies_to の要素はすべて文字列で指定してください (got {v!r})"
                )
            return cast(list[str], v)
        raise ValueError(
            f"applies_to はリストまたは文字列で指定してください (got {type(v).__name__})"
        )

    def matches_file(self, filepath: Path) -> bool:
        """applies_to パターンでファイルをフィルタリングします。

        filepath.name（ファイル名のみ）に対して fnmatch でマッチします。
        パス成分は考慮されません。applies_to が空の場合は全ファイルにマッチします。
        """
        if not self.applies_to:
            return True
        return any(fnmatch.fnmatch(filepath.name, pat) for pat in self.applies_to)


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
    supplement_messages: list[str] = Field(default_factory=list)


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
            ".git",
            ".venv",
            "__pycache__",
            "node_modules",
            ".kaizenlint",
        ]
    )
    extend_exclude: list[str] = Field(default_factory=list, alias="extend-exclude")
    force_exclude: bool = Field(default=False, alias="force-exclude")
    respect_gitignore: bool = Field(default=True, alias="respect-gitignore")
    rules: list[str] = Field(default_factory=lambda: ["rules/**/*.md"])
    show_rule: bool = Field(default=True, alias="show-rule")
    suppression: dict[str, list[SuppressionEntry]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_suppression_no_duplicates(self) -> Self:
        for file_path, entries in self.suppression.items():
            seen: set[str] = set()
            for entry in entries:
                if entry.rule in seen:
                    raise ValueError(
                        f"suppression の重複です。ファイル {file_path!r} にルール {entry.rule!r} が複数回定義されています。"
                    )
                seen.add(entry.rule)
        return self
