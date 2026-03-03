"""applies_to フィルタリングのテスト。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from kaizenlint.cli import _build_tasks
from kaizenlint.models import LintRule, LlmCheckerConfig, SuppressionEntry
from kaizenlint.rules import parse_rule_file


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


# ── モデル & validator ──


class TestLintRuleAppliesToField:
    def test_default_empty_list(self) -> None:
        rule = LintRule(
            title="t",
            description="d",
            checker=LlmCheckerConfig(),
        )
        assert rule.applies_to == []

    def test_stores_patterns(self) -> None:
        rule = _make_rule(["*.py", "*.md"])
        assert rule.applies_to == ["*.py", "*.md"]

    def test_none_normalizes_to_empty_list(self) -> None:
        rule = _make_rule(applies_to=None)
        assert rule.applies_to == []

    def test_string_normalizes_to_single_list(self) -> None:
        rule = _make_rule(applies_to="*.py")
        assert rule.applies_to == ["*.py"]

    def test_non_string_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            _make_rule(applies_to=42)

    def test_list_with_non_string_element_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            _make_rule(applies_to=["*.py", 123])


# ── パース (parse_rule_file) ──


class TestParseRuleFileAppliesToField:
    def test_reads_applies_to_from_frontmatter(self, tmp_path: Path) -> None:
        rule_file = tmp_path / "rule.md"
        rule_file.write_text(
            '---\napplies_to: ["*.py"]\n---\n## Test Rule\nDescription here.\n'
        )
        rules = parse_rule_file(rule_file)
        assert len(rules) == 1
        assert rules[0].applies_to == ["*.py"]

    def test_missing_applies_to_defaults_to_empty(self, tmp_path: Path) -> None:
        rule_file = tmp_path / "rule.md"
        rule_file.write_text("---\n---\n## Test Rule\nDescription here.\n")
        rules = parse_rule_file(rule_file)
        assert len(rules) == 1
        assert rules[0].applies_to == []

    def test_null_applies_to_defaults_to_empty(self, tmp_path: Path) -> None:
        rule_file = tmp_path / "rule.md"
        rule_file.write_text(
            "---\napplies_to: null\n---\n## Test Rule\nDescription here.\n"
        )
        rules = parse_rule_file(rule_file)
        assert len(rules) == 1
        assert rules[0].applies_to == []


# ── マッチング (matches_file) ──


class TestMatchesFile:
    def test_py_rule_skips_md_file(self) -> None:
        rule = _make_rule(["*.py"])
        assert not rule.matches_file(Path("docs/readme.md"))

    def test_py_rule_applies_to_py_file(self) -> None:
        rule = _make_rule(["*.py"])
        assert rule.matches_file(Path("src/main.py"))

    def test_empty_applies_to_matches_all(self) -> None:
        rule = _make_rule([])
        assert rule.matches_file(Path("anything.txt"))
        assert rule.matches_file(Path("code.py"))
        assert rule.matches_file(Path("doc.md"))

    def test_multiple_patterns(self) -> None:
        rule = _make_rule(["*.py", "*.md"])
        assert rule.matches_file(Path("main.py"))
        assert rule.matches_file(Path("readme.md"))
        assert not rule.matches_file(Path("data.csv"))

    def test_case_sensitive_on_linux(self) -> None:
        rule = _make_rule(["*.PY"])
        assert not rule.matches_file(Path("main.py"))

    def test_exact_filename_match(self) -> None:
        rule = _make_rule(["setup.cfg"])
        assert rule.matches_file(Path("project/setup.cfg"))
        assert not rule.matches_file(Path("project/setup.cfg.bak"))


# ── suppression 連携 (_build_tasks) ──


class TestBuildTasksSuppression:
    def test_applies_to_skip_marks_suppression_as_used(self, tmp_path: Path) -> None:
        """applies_to でスキップされたルールの suppression は used 扱いになる。"""
        # テスト用ファイル作成
        md_file = tmp_path / "readme.md"
        md_file.write_text("# Hello")

        rule = _make_rule(["*.py"], source_path="rules/py-only.md", title="py-rule")
        rule_key = f"{rule.source_path}:{rule.title}"
        rel_file = "readme.md"

        suppression_index: dict[tuple[str, str], SuppressionEntry] = {
            (rel_file, rule_key): SuppressionEntry(rule=rule_key),
        }

        tasks, task_keys, used_suppressions = _build_tasks(
            resolved=[md_file],
            rules=[rule],
            project_root=tmp_path,
            suppression_index=suppression_index,
        )

        # タスクには含まれない（applies_to でスキップ）
        assert len(tasks) == 0
        # suppression は used 扱い
        assert (rel_file, rule_key) in used_suppressions

    def test_matching_rule_creates_task(self, tmp_path: Path) -> None:
        """applies_to にマッチするファイルはタスクが生成される。"""
        py_file = tmp_path / "main.py"
        py_file.write_text("print('hello')")

        rule = _make_rule(["*.py"], source_path="rules/py-only.md", title="py-rule")

        tasks, task_keys, used_suppressions = _build_tasks(
            resolved=[py_file],
            rules=[rule],
            project_root=tmp_path,
            suppression_index={},
        )

        assert len(tasks) == 1
        assert tasks[0].rule.title == "py-rule"
