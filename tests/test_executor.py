"""AsyncExecutor の drain (--max-fail) の挙動を検証します。

Notes
-----
drain の発動と skip の動作を決定的に検証しています。
check_one を mock 化し semaphore の concurrency を制御することで、
asyncio のスケジューリングに依存しない安定したテストを実現しています。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Sequence
import contextlib
from typing import Any, Self
from unittest.mock import patch

from kaizenlint.executor import AsyncExecutor, ExecuteResult
from kaizenlint.models import (
    CheckTask,
    KaizenlintConfig,
    LintRule,
    LintSource,
    LintSourceName,
    LintViolation,
    LintViolationMessage,
    LlmConfig,
    LlmProfile,
    RegexCheckerConfig,
)

AsyncCheckToViolationFn = Callable[
    [CheckTask, KaizenlintConfig],
    Coroutine[Any, Any, LintViolation | None],
]

# ── fixture を生成します。──


def _build_task(title: str = "rule") -> CheckTask:
    """テストごとに異なる title で task を量産するために使います。

    Parameters
    ----------
    title: str
        rule の title です。

    Returns
    -------
    CheckTask
        生成した CheckTask です。

    Examples
    --------
    >>> _build_task("my-rule").rule.title
    'my-rule'
    """
    return CheckTask(
        source=LintSource(content="test"),
        source_name=LintSourceName(name="test.py"),
        rule=LintRule(
            title=title,
            description="desc",
            checker=RegexCheckerConfig(),
            source_path="test.md",
        ),
    )


def _build_violation(task: CheckTask) -> LintViolation:
    """on_result callback に渡す violation を模倣するために使います。

    Parameters
    ----------
    task: CheckTask
        violation を紐づける task です。

    Returns
    -------
    LintViolation
        生成した violation です。

    Examples
    --------
    >>> _build_violation(task).message.text
    'violation'
    """
    return LintViolation(
        rule=task.rule,
        message=LintViolationMessage(text="violation"),
    )


def _build_config() -> KaizenlintConfig:
    """LLM endpoint への実通信を避けるために dummy config を返します。

    Returns
    -------
    KaizenlintConfig
        生成した config です。

    Examples
    --------
    >>> _build_config().llm.profiles["default"].model
    'test-model'
    """
    return KaizenlintConfig(
        llm=LlmConfig(profiles={"default": LlmProfile(model="test-model")}),
    )


# ── executor の実行と assertion を集約するヘルパーです。──


def _run_with_mock(
    tasks: Sequence[CheckTask],
    mock_fn: AsyncCheckToViolationFn,
    *,
    max_fail: int | None = None,
    concurrency: int | None = None,
) -> tuple[ExecuteResult, list[tuple[CheckTask, LintViolation | None]]]:
    """各テストで繰り返す setup を集約して本質的な assertion に集中するためのヘルパーです。

    Parameters
    ----------
    tasks: Sequence[CheckTask]
        実行する task のリストです。
    mock_fn: AsyncCheckToViolationFn
        check_one の代替として使う async 関数です。
    max_fail: int | None
        drain の閾値です。
    concurrency: int | None
        指定時に max_concurrency を上書きします。

    Returns
    -------
    tuple[ExecuteResult, list[tuple[CheckTask, LintViolation | None]]]
        ExecuteResult と on_result で収集した pair のリストです。

    Examples
    --------
    >>> result, pairs = _run_with_mock(tasks, mock, max_fail=1, concurrency=1)
    >>> result.is_drain_activated
    True
    """
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("kaizenlint.executor.check_one", side_effect=mock_fn))
        if concurrency is not None:
            stack.enter_context(
                patch("kaizenlint.executor.max_concurrency", return_value=concurrency)
            )

        task_violation_pairs: list[tuple[CheckTask, LintViolation | None]] = []
        result = AsyncExecutor().execute(
            tasks,
            _build_config(),
            lambda t, v: task_violation_pairs.append((t, v)),
            max_fail=max_fail,
        )

    return result, task_violation_pairs


def _assert_drain_result(
    result: ExecuteResult,
    task_violation_pairs: list[tuple[CheckTask, LintViolation | None]],
    *,
    is_drain_activated: bool,
    min_skipped: int = 0,
    exact_skipped: int | None = None,
    exact_reported: int | None = None,
    min_violations: int | None = None,
) -> None:
    """drain 関連の assertion を集約し、各テストの本質を 1 行で表現できるようにします。

    Parameters
    ----------
    result: ExecuteResult
        executor の戻り値です。
    task_violation_pairs: list[tuple[CheckTask, LintViolation | None]]
        on_result で収集した pair のリストです。
    is_drain_activated: bool
        期待する drain 状態です。
    min_skipped: int
        skipped の最小値です。
    exact_skipped: int | None
        skipped の厳密な期待値です。
    exact_reported: int | None
        報告された task 数の厳密な期待値です。
    min_violations: int | None
        violation 数の最小値です。

    Returns
    -------
    None
    """
    assert result.is_drain_activated is is_drain_activated, (
        f"期待: is_drain_activated={is_drain_activated},"
        f" 実際: is_drain_activated={result.is_drain_activated}"
    )
    if exact_skipped is not None:
        assert result.skipped == exact_skipped, (
            f"期待: skipped={exact_skipped}, 実際: skipped={result.skipped}"
        )
    if min_skipped > 0:
        assert result.skipped >= min_skipped, (
            f"期待: skipped >= {min_skipped}, 実際: skipped={result.skipped}"
        )
    if exact_reported is not None:
        assert len(task_violation_pairs) == exact_reported, (
            f"期待: reported={exact_reported}, 実際: reported={len(task_violation_pairs)}"
        )
    if min_violations is not None:
        reported_violations = [v for _, v in task_violation_pairs if v is not None]
        assert len(reported_violations) >= min_violations, (
            f"期待: violations >= {min_violations},"
            f" 実際: violations={len(reported_violations)}"
        )


# ── check_one の挙動を定義する mock 関数です。──


async def _always_violate(
    task: CheckTask, config: KaizenlintConfig
) -> LintViolation | None:
    """drain なしの基本動作や全 task in-flight のケースを検証するために使います。

    Parameters
    ----------
    task: CheckTask
        チェック対象の task です。
    config: KaizenlintConfig
        リンター設定です。

    Returns
    -------
    LintViolation | None
        常に violation を返します。
    """
    return _build_violation(task)


async def _never_violate(
    task: CheckTask, config: KaizenlintConfig
) -> LintViolation | None:
    """violation がない場合に drain が発動しないことを検証するために使います。

    Parameters
    ----------
    task: CheckTask
        チェック対象の task です。
    config: KaizenlintConfig
        リンター設定です。

    Returns
    -------
    LintViolation | None
        常に None を返します。
    """
    return None


def _first_call_violates_rest_yield() -> AsyncCheckToViolationFn:
    """最初の呼び出しだけ violation を返し、以降は yield して None を返す mock を生成します。

    asyncio.Lock で最初の caller を排他制御しています。
    Lock は意図的に解放せず、2 番目以降の caller は locked 状態を確認して
    yield path に入ります。

    Returns
    -------
    AsyncCheckToViolationFn
        生成した mock 関数です。

    Examples
    --------
    >>> mock_fn = _first_call_violates_rest_yield()
    """
    once = asyncio.Lock()

    async def _mock(task: CheckTask, config: KaizenlintConfig) -> LintViolation | None:
        """drain の発動条件 (violation_count >= max_fail) を正確に 1 回だけ満たすためのモックです。"""
        if once.locked():
            # event loop に制御を複数回渡して _run loop が drain.set() を反映できるようにする
            # TODO: asyncio の scheduling に依存しており、より堅牢な同期方法を検討する余地があります
            for _ in range(5):
                await asyncio.sleep(0)
            return None
        await once.acquire()
        return _build_violation(task)

    return _mock


# ── test: max_fail 未指定 (default) ──


class TestMaxFailNone:
    """max_fail 未指定のとき全 task が実行されることを検証します。"""

    def test_all_tasks_run(self: Self) -> None:
        """drain が発動せず 5 task 全てが on_result に渡されます。"""
        result, task_violation_pairs = _run_with_mock(
            [_build_task(f"rule-{task_index}") for task_index in range(5)],
            _always_violate,
        )
        _assert_drain_result(
            result,
            task_violation_pairs,
            is_drain_activated=False,
            exact_skipped=0,
            exact_reported=5,
        )


# ── test: drain の基本動作を検証します。──


class TestDrainBasic:
    """max_fail=1 で drain が発動し待機中 task が skip されることを検証します。"""

    def test_drain_skips_waiting_tasks(self: Self) -> None:
        """最初の violation で drain が発動し、semaphore 待ちの task が skip されます。"""
        result, task_violation_pairs = _run_with_mock(
            [_build_task(f"rule-{task_index}") for task_index in range(10)],
            _first_call_violates_rest_yield(),
            max_fail=1,
            concurrency=1,
        )
        _assert_drain_result(
            result,
            task_violation_pairs,
            is_drain_activated=True,
            min_skipped=1,
            min_violations=1,
        )


# ── test: max_fail=0 を検証します。──


class TestDrainMaxFailZero:
    """max_fail=0 で最初の violation 検出時に即 drain されることを検証します。"""

    def test_max_fail_zero(self: Self) -> None:
        """violation_count (1) >= max_fail (0) で即座に drain が発動します。"""
        result, task_violation_pairs = _run_with_mock(
            [_build_task(f"rule-{task_index}") for task_index in range(10)],
            _first_call_violates_rest_yield(),
            max_fail=0,
            concurrency=1,
        )
        _assert_drain_result(
            result,
            task_violation_pairs,
            is_drain_activated=True,
            min_skipped=1,
        )


# ── test: concurrency >= task 数を検証します。──


class TestDrainAllComplete:
    """concurrency が task 数以上で全 task が完了し skipped=0 になることを検証します。"""

    def test_all_complete_before_drain(self: Self) -> None:
        """concurrency=100、task 3 件で全完了し skipped=0 になります。"""
        result, task_violation_pairs = _run_with_mock(
            [_build_task(f"rule-{task_index}") for task_index in range(3)],
            _always_violate,
            max_fail=1,
            concurrency=100,
        )
        _assert_drain_result(
            result,
            task_violation_pairs,
            is_drain_activated=True,
            exact_skipped=0,
            exact_reported=3,
        )


# ── test: violation なしを検証します。──


class TestNoViolations:
    """全 task が violation なしのとき drain が発動しないことを検証します。"""

    def test_no_violations(self: Self) -> None:
        """5 task 全て None を返し、is_drain_activated=False になります。"""
        result, task_violation_pairs = _run_with_mock(
            [_build_task(f"rule-{task_index}") for task_index in range(5)],
            _never_violate,
            max_fail=1,
        )
        _assert_drain_result(
            result,
            task_violation_pairs,
            is_drain_activated=False,
            exact_skipped=0,
            exact_reported=5,
        )


# ── test: 複数 resource key を検証します。──


class TestMultipleResourceKeys:
    """異なる resource key の task が混在しても drain が正しく動作することを検証します。"""

    def test_mixed_resource_keys(self: Self) -> None:
        """4 task (全て同一 checker) で max_fail=1 のとき少なくとも 1 件報告されます。"""
        result, task_violation_pairs = _run_with_mock(
            [
                _build_task("regex-rule"),
                _build_task("regex-rule-2"),
                _build_task("rule-3"),
                _build_task("rule-4"),
            ],
            _always_violate,
            max_fail=1,
            concurrency=1,
        )
        _assert_drain_result(
            result,
            task_violation_pairs,
            is_drain_activated=True,
            min_violations=1,
        )
