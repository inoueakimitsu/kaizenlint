"""チェック タスクの実行戦略を提供します。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Protocol

from kaizenlint.checker import check_one, max_concurrency, resource_key
from kaizenlint.models import CheckTask, KaizenlintConfig, LintViolation

ResultCallback = Callable[[CheckTask, LintViolation | None], None]


class Executor(Protocol):
    """チェック タスクの実行を統括するプロトコルです。"""

    def execute(
        self,
        tasks: Sequence[CheckTask],
        config: KaizenlintConfig,
        on_result: ResultCallback,
    ) -> None:
        """タスクを実行し、完了したタスクから on_result を呼びます。

        Parameters
        ----------
        tasks: Sequence[CheckTask]
            実行するチェック タスクです。
        config: KaizenlintConfig
            リンター設定です。
        on_result: ResultCallback
            タスク完了時に呼ばれるコールバックです。例外発生時は即中断します。

        Returns
        -------
        None
        """
        ...


class AsyncExecutor:
    """asyncio とエンドポイント単位セマフォによる並列実行を提供します。"""

    def execute(
        self,
        tasks: Sequence[CheckTask],
        config: KaizenlintConfig,
        on_result: ResultCallback,
    ) -> None:
        """タスクを並列実行し、完了順に on_result を呼びます。

        Parameters
        ----------
        tasks: Sequence[CheckTask]
            実行するチェック タスクです。
        config: KaizenlintConfig
            リンター設定です。
        on_result: ResultCallback
            タスク完了時に呼ばれるコールバックです。

        Returns
        -------
        None
        """
        # 注意: 既存のイベントループ内から呼ぶと RuntimeError になります。
        asyncio.run(self._run(tasks, config, on_result))

    async def _run(
        self,
        tasks: Sequence[CheckTask],
        config: KaizenlintConfig,
        on_result: ResultCallback,
    ) -> None:
        """全タスクを並列にスケジュールし、完了順にコールバックを実行します。"""
        # 同一エンドポイントへの同時リクエスト数を制限するため、
        # リソース キーごとにセマフォを構築しつつコルーチンを生成します。
        semaphores: dict[str, asyncio.Semaphore] = {}
        coros = []
        for task in tasks:
            checker = task.rule.checker
            key = resource_key(checker, config)
            if key not in semaphores:
                semaphores[key] = asyncio.Semaphore(max_concurrency(checker, config))
            coros.append(self._run_one(task, config, semaphores[key]))

        # ユーザーへのリアルタイム フィードバックのため、
        # 完了順にコールバックを呼びます。
        for coro in asyncio.as_completed(coros):
            task, violation = await coro
            on_result(task, violation)

    async def _run_one(
        self,
        task: CheckTask,
        config: KaizenlintConfig,
        semaphore: asyncio.Semaphore,
    ) -> tuple[CheckTask, LintViolation | None]:
        """セマフォで制御しながら単一タスクを実行します。"""
        async with semaphore:
            violation = await check_one(task, config)
            return (task, violation)
