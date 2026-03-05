"""チェック タスクの実行戦略を提供します。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from kaizenlint.checker import check_one, max_concurrency, resource_key
from kaizenlint.models import CheckTask, KaizenlintConfig, LintViolation

ResultCallback = Callable[[CheckTask, LintViolation | None], None]


@dataclass(frozen=True, slots=True)
class ExecuteResult:
    """execute の戻り値です。"""

    skipped: int
    is_drain_activated: bool


class Executor(Protocol):
    """チェック タスクの実行を統括するプロトコルです。"""

    def execute(
        self,
        tasks: Sequence[CheckTask],
        config: KaizenlintConfig,
        on_result: ResultCallback,
        *,
        max_fail: int | None = None,
    ) -> ExecuteResult:
        """タスクを実行し、完了したタスクから on_result を呼びます。

        Parameters
        ----------
        tasks: Sequence[CheckTask]
            実行するチェック タスクです。
        config: KaizenlintConfig
            リンター設定です。
        on_result: ResultCallback
            タスク完了時に呼ばれるコールバックです。例外発生時は即中断します。
        max_fail: int | None
            この件数の違反を検出した時点で残りのタスクをスキップします。
            None の場合は全タスクを実行します。

        Returns
        -------
        ExecuteResult
        """
        ...


class AsyncExecutor:
    """asyncio とエンドポイント単位セマフォによる並列実行を提供します。"""

    def execute(
        self,
        tasks: Sequence[CheckTask],
        config: KaizenlintConfig,
        on_result: ResultCallback,
        *,
        max_fail: int | None = None,
    ) -> ExecuteResult:
        """タスクを並列実行し、完了順に on_result を呼びます。

        Parameters
        ----------
        tasks: Sequence[CheckTask]
            実行するチェック タスクです。
        config: KaizenlintConfig
            リンター設定です。
        on_result: ResultCallback
            タスク完了時に呼ばれるコールバックです。
        max_fail: int | None
            この件数の違反を検出した時点で残りのタスクをスキップします。

        Returns
        -------
        ExecuteResult
        """
        # 注意: 既存のイベントループ内から呼ぶと RuntimeError になります。
        return asyncio.run(self._run(tasks, config, on_result, max_fail))

    async def _run(
        self,
        tasks: Sequence[CheckTask],
        config: KaizenlintConfig,
        on_result: ResultCallback,
        max_fail: int | None = None,
    ) -> ExecuteResult:
        """全タスクを並列にスケジュールし、完了順にコールバックを実行します。"""
        # 同一エンドポイントへの同時リクエスト数を制限するため、
        # リソース キーごとにセマフォを構築しつつコルーチンを生成します。
        semaphores: dict[str, asyncio.Semaphore] = {}
        drain: asyncio.Event | None = asyncio.Event() if max_fail is not None else None
        violation_count = 0
        skipped_count = 0
        is_drain_activated = False
        coros = []

        for task in tasks:
            checker = task.rule.checker
            key = resource_key(checker, config)
            if key not in semaphores:
                semaphores[key] = asyncio.Semaphore(max_concurrency(checker, config))
            coros.append(self._run_one(task, config, semaphores[key], drain))

        # ユーザーへのリアルタイム フィードバックのため、
        # 完了順にコールバックを呼びます。
        for coro in asyncio.as_completed(coros):
            result = await coro
            if result is None:
                skipped_count += 1
                continue
            task_result, violation = result
            on_result(task_result, violation)
            if violation is not None and drain is not None and max_fail is not None:
                violation_count += 1
                if violation_count >= max_fail:
                    drain.set()
                    is_drain_activated = True

        return ExecuteResult(
            skipped=skipped_count, is_drain_activated=is_drain_activated
        )

    async def _run_one(
        self,
        task: CheckTask,
        config: KaizenlintConfig,
        semaphore: asyncio.Semaphore,
        drain: asyncio.Event | None = None,
    ) -> tuple[CheckTask, LintViolation | None] | None:
        """セマフォで制御しながら単一タスクを実行します。"""
        if drain is not None and drain.is_set():
            return None
        async with semaphore:
            if drain is not None and drain.is_set():
                return None
            violation = await check_one(task, config)
            return (task, violation)
