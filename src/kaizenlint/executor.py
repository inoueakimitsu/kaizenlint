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
        """タスクを実行し結果を返す。順序は実装依存。"""
        ...


class AsyncExecutor:
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
        semaphores: dict[str, asyncio.Semaphore] = {}
        for task in tasks:
            key = resource_key(task.rule.checker, config)
            if key not in semaphores:
                limit = max_concurrency(task.rule.checker, config)
                semaphores[key] = asyncio.Semaphore(limit)

        coros = [
            self._run_one(
                task, config, semaphores[resource_key(task.rule.checker, config)]
            )
            for task in tasks
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

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
