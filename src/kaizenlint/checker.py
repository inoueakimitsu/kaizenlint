"""LLM によるルール チェック ロジックを提供します。

並行制御は executor モジュールの責務です。
このモジュールは純粋なチェック処理とリソース情報の提供のみを行います。
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
    """同じリソースを共有するタスクのグルーピング キーを返します。"""
    if isinstance(checker, LlmCheckerConfig):
        profile = config.llm.profiles[checker.profile]
        return f"llm:{profile.endpoint}"
    return f"checker:{checker.type}"


def max_concurrency(checker: CheckerConfig, config: KaizenlintConfig) -> int:
    """リソース キーごとの同時実行上限を返します。"""
    if isinstance(checker, LlmCheckerConfig):
        profile = config.llm.profiles[checker.profile]
        endpoint = config.llm.endpoints.get(profile.endpoint)
        if endpoint:
            return endpoint.max_concurrency
        return config.executor.default_concurrency
    return config.executor.default_concurrency


# --- チェック実行 ---


def _build_messages(task: CheckTask) -> list[ChatCompletionMessageParam]:
    """LLM に送信するメッセージ リストを構築します。"""
    source_name = task.source_name.name or "(unknown)"
    user_content = (
        f"ファイル名: {source_name}\n\n"
        f"## ルール: {task.rule.title}\n{task.rule.description}\n\n"
        f"## 対象テキスト\n```\n{task.source.content}\n```"
    )
    if task.supplement_messages:
        supplement_text = "\n".join(
            f"- {msg}" for msg in task.supplement_messages
        )
        user_content += (
            f"\n\n## 例外事項 (プロジェクトの方針として許容されている設計判断)\n"
            f"{supplement_text}\n\n"
            f"上記の例外事項に該当するコードは、ルール違反として報告しないでください。"
            f"例外事項に該当しない部分のみを違反として判定してください。"
        )
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
            "content": user_content,
        },
    ]


async def check_one(
    task: CheckTask,
    config: KaizenlintConfig,
) -> LintViolation | None:
    """1 つのタスク (ソース x ルール) をチェックします。"""
    if not isinstance(task.rule.checker, LlmCheckerConfig):
        return None

    checker = task.rule.checker
    profile = config.llm.profiles[checker.profile]
    endpoint = config.llm.endpoints.get(profile.endpoint)
    base_url = endpoint.base_url if endpoint else None
    client = openai.AsyncOpenAI(base_url=base_url)

    extra_kwargs: dict[str, object] = {}
    if profile.temperature is not None:
        extra_kwargs["temperature"] = profile.temperature

    messages = _build_messages(task)
    completion = await client.chat.completions.parse(
        model=profile.model,
        messages=messages,
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
