"""チェックタスクの実行戦略。

Executor プロトコルを定義し、AsyncExecutor で asyncio ベースの並列実行を提供する。
将来 CeleryExecutor 等を追加する際は Executor プロトコルに従う。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from typing import Protocol

from kaizenlint.checker import check_one, max_concurrency, resource_key
from kaizenlint.models import CheckTask, KaizenlintConfig, LintViolation


class Executor(Protocol):
    def execute(
        self,
        tasks: Sequence[CheckTask],
        config: KaizenlintConfig,
    ) -> Iterable[tuple[CheckTask, LintViolation | None]]:
        """タスクを実行し結果を返します。順序は実装依存です。"""
        ...


class AsyncExecutor:
    """asyncio + エンドポイント単位セマフォによる並列実行。"""

    def execute(
        self,
        tasks: Sequence[CheckTask],
        config: KaizenlintConfig,
    ) -> list[tuple[CheckTask, LintViolation | None]]:
        return asyncio.run(self._run(tasks, config))

    async def _run(
        self,
        tasks: Sequence[CheckTask],
        config: KaizenlintConfig,
    ) -> list[tuple[CheckTask, LintViolation | None]]:
        # リソースキーごとにセマフォを構築
        semaphores: dict[str, asyncio.Semaphore] = {}
        task_keys: list[str] = []
        for task in tasks:
            key = resource_key(task.rule.checker, config)
            task_keys.append(key)
            if key not in semaphores:
                limit = max_concurrency(task.rule.checker, config)
                semaphores[key] = asyncio.Semaphore(limit)

        # 全タスクを並列実行
        coros = [
            self._run_one(task, config, semaphores[key])
            for task, key in zip(tasks, task_keys)
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

        # 結果を収集
        output: list[tuple[CheckTask, LintViolation | None]] = []
        for task, result in zip(tasks, results):
            if isinstance(result, BaseException):
                raise result
            output.append((task, result))
        return output

    async def _run_one(
        self,
        task: CheckTask,
        config: KaizenlintConfig,
        semaphore: asyncio.Semaphore,
    ) -> LintViolation | None:
        async with semaphore:
            return await check_one(task, config)
