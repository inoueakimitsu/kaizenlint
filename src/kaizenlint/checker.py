"""LLM によるルールチェックロジック。

並行制御は executor モジュールの責務。
このモジュールは純粋なチェック処理とリソース情報の提供のみを行う。
"""

import openai
from openai.types.chat import ChatCompletionMessageParam

from kaizenlint.models import (
    CheckTask,
    CheckerConfig,
    KaizenlintConfig,
    LintViolation,
    LintViolationMessage,
    LlmCheckerConfig,
    _LlmJudgement,
)


# --- リソース管理 ---


def resource_key(checker: CheckerConfig, config: KaizenlintConfig) -> str:
    """同じリソースを共有するタスクのグルーピングキーを返します。"""
    if isinstance(checker, LlmCheckerConfig):
        profile = config.llm.profiles[checker.profile]
        return f"llm:{profile.endpoint}"
    return f"checker:{checker.type}"


def max_concurrency(checker: CheckerConfig, config: KaizenlintConfig) -> int:
    """リソースキーごとの同時実行上限を返します。"""
    if not isinstance(checker, LlmCheckerConfig):
        return config.executor.default_concurrency
    profile = config.llm.profiles[checker.profile]
    endpoint = config.llm.endpoints.get(profile.endpoint)
    if endpoint:
        return endpoint.max_concurrency
    return config.executor.default_concurrency


# --- チェック実行 ---


def _build_messages(task: CheckTask) -> list[ChatCompletionMessageParam]:
    """LLM に送信するメッセージリストを構築します。"""
    source_name = task.source_name.name or "(unknown)"
    return [
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
                f"ファイル名: {source_name}\n\n"
                f"## ルール: {task.rule.title}\n{task.rule.description}\n\n"
                f"## 対象テキスト\n```\n{task.source.content}\n```"
            ),
        },
    ]


async def check_one(
    task: CheckTask,
    config: KaizenlintConfig,
) -> LintViolation | None:
    """1 つのタスク (ソース x ルール) をチェックします。"""
    if not isinstance(task.rule.checker, LlmCheckerConfig):
        return None

    # クライアント準備
    checker = task.rule.checker
    profile = config.llm.profiles[checker.profile]
    endpoint = config.llm.endpoints.get(profile.endpoint)
    base_url = endpoint.base_url if endpoint else None
    client = openai.AsyncOpenAI(base_url=base_url)

    extra_kwargs: dict[str, object] = {}
    if profile.temperature is not None:
        extra_kwargs["temperature"] = profile.temperature

    # LLM 呼び出し
    messages = _build_messages(task)
    completion = await client.chat.completions.parse(
        model=profile.model,
        messages=messages,
        response_format=_LlmJudgement,
        **extra_kwargs,  # type: ignore[invalid-argument-type]
    )

    # 結果判定
    judgement = completion.choices[0].message.parsed
    if judgement is None:
        return None
    if judgement.violated:
        return LintViolation(
            rule=task.rule,
            message=LintViolationMessage(text=judgement.message),
        )
    return None
