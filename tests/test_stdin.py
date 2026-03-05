"""stdin モードのテスト。"""

from pathlib import Path
from unittest.mock import patch

import pytest

from kaizenlint.cli import _build_tasks
from kaizenlint.models import (
    LintRule,
    LintSource,
    LintSourceName,
    LlmCheckerConfig,
    SuppressionEntry,
)


def _make_rule(applies_to: object = None, **kwargs: object) -> LintRule:
    defaults: dict[str, object] = {
        "title": "test-rule",
        "description": "test description",
        "checker": LlmCheckerConfig(),
        "source_path": "test.md",
    }
    if applies_to is not None:
        defaults["applies_to"] = applies_to
    defaults.update(kwargs)
    return LintRule(**defaults)  # type: ignore[arg-type]


# ── _build_tasks stdin_source テスト ──


class TestBuildTasksStdinSource:
    def test_stdin_source_creates_task(self) -> None:
        """stdin_source が指定された場合、タスクが生成される。"""
        rule = _make_rule(["*.py"], source_path="rules/test.md", title="py-rule")
        source = LintSource(content="print('hello')")
        source_name = LintSourceName(name="test.py")
        filepath = Path("test.py")

        tasks, task_keys, used = _build_tasks(
            resolved=[],
            rules=[rule],
            project_root=Path("/project"),
            suppression_index={},
            stdin_source=(source, source_name, filepath, None),
        )

        assert len(tasks) == 1
        assert tasks[0].source.content == "print('hello')"
        assert tasks[0].source_name.name == "test.py"

    def test_stdin_source_applies_to_filters(self) -> None:
        """stdin_source でも applies_to フィルタが効く。"""
        rule = _make_rule(["*.py"], source_path="rules/test.md", title="py-rule")
        source = LintSource(content="# readme")
        source_name = LintSourceName(name="readme.md")
        filepath = Path("readme.md")

        tasks, _, _ = _build_tasks(
            resolved=[],
            rules=[rule],
            project_root=Path("/project"),
            suppression_index={},
            stdin_source=(source, source_name, filepath, None),
        )

        assert len(tasks) == 0

    def test_stdin_source_skip_applies_to(self) -> None:
        """skip_applies_to=True のとき全ルールが適用される。"""
        rule = _make_rule(["*.py"], source_path="rules/test.md", title="py-rule")
        source = LintSource(content="# readme")
        source_name = LintSourceName(name="<stdin>")
        filepath = Path("<stdin>")

        tasks, _, _ = _build_tasks(
            resolved=[],
            rules=[rule],
            project_root=Path("/project"),
            suppression_index={},
            stdin_source=(source, source_name, filepath, None),
            skip_applies_to=True,
        )

        assert len(tasks) == 1

    def test_stdin_source_suppression_applied(self) -> None:
        """stdin_source でも suppression が適用される。"""
        rule = _make_rule(["*.py"], source_path="rules/test.md", title="py-rule")
        rule_key = f"{rule.source_path}:{rule.title}"
        rel_file = "src/test.py"

        source = LintSource(content="print('hello')")
        source_name = LintSourceName(name="src/test.py")
        filepath = Path("src/test.py")

        suppression_index = {
            (rel_file, rule_key): SuppressionEntry(rule=rule_key),
        }

        tasks, _, used = _build_tasks(
            resolved=[],
            rules=[rule],
            project_root=Path("/project"),
            suppression_index=suppression_index,
            stdin_source=(source, source_name, filepath, rel_file),
        )

        # suppression で skip されるためタスクなし
        assert len(tasks) == 0
        assert (rel_file, rule_key) in used

    def test_stdin_source_suppression_with_messages(self) -> None:
        """stdin_source で messages 付き suppression が適用される。"""
        rule = _make_rule(["*.py"], source_path="rules/test.md", title="py-rule")
        rule_key = f"{rule.source_path}:{rule.title}"
        rel_file = "src/test.py"

        source = LintSource(content="print('hello')")
        source_name = LintSourceName(name="src/test.py")
        filepath = Path("src/test.py")

        suppression_index = {
            (rel_file, rule_key): SuppressionEntry(
                rule=rule_key, messages=["意図的です"]
            ),
        }

        tasks, _, used = _build_tasks(
            resolved=[],
            rules=[rule],
            project_root=Path("/project"),
            suppression_index=suppression_index,
            stdin_source=(source, source_name, filepath, rel_file),
        )

        # messages 付きなのでタスクは生成されるが supplement_messages が設定される
        assert len(tasks) == 1
        assert tasks[0].supplement_messages == ["意図的です"]
        assert (rel_file, rule_key) in used

    def test_stdin_source_ignores_resolved(self) -> None:
        """stdin_source 指定時は resolved が無視される。"""
        rule = _make_rule(source_path="rules/test.md", title="all-rule")
        source = LintSource(content="stdin content")
        source_name = LintSourceName(name="<stdin>")
        filepath = Path("<stdin>")

        tasks, _, _ = _build_tasks(
            resolved=[],  # 空でもタスクが生成される
            rules=[rule],
            project_root=Path("/project"),
            suppression_index={},
            stdin_source=(source, source_name, filepath, None),
            skip_applies_to=True,
        )

        assert len(tasks) == 1
        assert tasks[0].source.content == "stdin content"

    def test_stdin_source_task_keys_uses_rel_file(self) -> None:
        """task_keys に rel_file が使われる。"""
        rule = _make_rule(["*.py"], source_path="rules/test.md", title="py-rule")
        rel_file = "src/main.py"

        source = LintSource(content="code")
        source_name = LintSourceName(name="src/main.py")
        filepath = Path("src/main.py")

        tasks, task_keys, _ = _build_tasks(
            resolved=[],
            rules=[rule],
            project_root=Path("/project"),
            suppression_index={},
            stdin_source=(source, source_name, filepath, rel_file),
        )

        assert len(tasks) == 1
        tk = task_keys[id(tasks[0])]
        assert tk == ("src/main.py", "rules/test.md:py-rule")

    def test_stdin_source_task_keys_without_rel_file(self) -> None:
        """rel_file が None のとき task_keys にはファイル名が使われる。"""
        rule = _make_rule(source_path="rules/test.md", title="all-rule")

        source = LintSource(content="code")
        source_name = LintSourceName(name="<stdin>")
        filepath = Path("<stdin>")

        tasks, task_keys, _ = _build_tasks(
            resolved=[],
            rules=[rule],
            project_root=Path("/project"),
            suppression_index={},
            stdin_source=(source, source_name, filepath, None),
            skip_applies_to=True,
        )

        assert len(tasks) == 1
        tk = task_keys[id(tasks[0])]
        assert tk == ("<stdin>", "rules/test.md:all-rule")
