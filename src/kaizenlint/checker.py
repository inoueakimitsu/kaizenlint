import openai

from kaizenlint.models import (
    KaizenlintConfig,
    LintRule,
    LintSource,
    LintSourceName,
    LintViolation,
    LintViolationMessage,
    LlmCheckerConfig,
    _LlmJudgement,
)


def _check_one_rule(
    source: LintSource,
    source_name: LintSourceName,
    rule: LintRule,
    config: KaizenlintConfig,
) -> LintViolation | None:
    if not isinstance(rule.checker, LlmCheckerConfig):
        return None

    profile = config.llm.profiles[rule.checker.profile]
    client = openai.OpenAI(base_url=profile.base_url)

    extra_kwargs: dict[str, object] = {}
    if profile.temperature is not None:
        extra_kwargs["temperature"] = profile.temperature

    completion = client.chat.completions.parse(
        model=profile.model,
        messages=[
            {
                "role": "system",
                "content": (
                    "あなたは文書・コードの品質チェッカーです。"
                    "与えられたルールに対して、入力テキストが違反しているか判定してください。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"ファイル名: {source_name.name or '(unknown)'}\n\n"
                    f"## ルール: {rule.title}\n{rule.description}\n\n"
                    f"## 対象テキスト\n```\n{source.content}\n```"
                ),
            },
        ],
        response_format=_LlmJudgement,
        **extra_kwargs,  # type: ignore[invalid-argument-type]
    )

    judgement = completion.choices[0].message.parsed
    if judgement is None:
        return None
    if judgement.violated:
        return LintViolation(
            rule=rule,
            message=LintViolationMessage(text=judgement.message),
        )
    return None


def check(
    source: LintSource,
    source_name: LintSourceName,
    rules: list[LintRule],
    config: KaizenlintConfig,
) -> list[LintViolation]:
    violations: list[LintViolation] = []
    for rule in rules:
        result = _check_one_rule(source, source_name, rule, config)
        if result is not None:
            violations.append(result)
    return violations
