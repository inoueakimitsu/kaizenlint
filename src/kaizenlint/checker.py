import openai

from kaizenlint.models import (
    CheckTask,
    CheckerConfig,
    KaizenlintConfig,
    LintViolation,
    LintViolationMessage,
    LlmCheckerConfig,
    _LlmJudgement,
)


def resource_key(checker: CheckerConfig, config: KaizenlintConfig) -> str:
    """同じリソースを共有するタスクのグルーピングキーを返す。"""
    if isinstance(checker, LlmCheckerConfig):
        profile = config.llm.profiles[checker.profile]
        return f"llm:{profile.endpoint}"
    return f"checker:{checker.type}"


def max_concurrency(checker: CheckerConfig, config: KaizenlintConfig) -> int:
    """リソースキーごとの同時実行上限を返す。"""
    if isinstance(checker, LlmCheckerConfig):
        profile = config.llm.profiles[checker.profile]
        endpoint = config.llm.endpoints.get(profile.endpoint)
        if endpoint:
            return endpoint.max_concurrency
    return config.executor.default_concurrency


async def check_one(
    task: CheckTask,
    config: KaizenlintConfig,
) -> LintViolation | None:
    """1つのタスク（ソース×ルール）をチェックする。"""
    if not isinstance(task.rule.checker, LlmCheckerConfig):
        return None

    profile = config.llm.profiles[task.rule.checker.profile]
    endpoint = config.llm.endpoints.get(profile.endpoint)
    base_url = endpoint.base_url if endpoint else None
    client = openai.AsyncOpenAI(base_url=base_url)

    extra_kwargs: dict[str, object] = {}
    if profile.temperature is not None:
        extra_kwargs["temperature"] = profile.temperature

    completion = await client.chat.completions.parse(
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
                    f"ファイル名: {task.source_name.name or '(unknown)'}\n\n"
                    f"## ルール: {task.rule.title}\n{task.rule.description}\n\n"
                    f"## 対象テキスト\n```\n{task.source.content}\n```"
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
            rule=task.rule,
            message=LintViolationMessage(text=judgement.message),
        )
    return None
