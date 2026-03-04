"""kaizenlint の CLI エントリ ポイントを提供します。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from kaizenlint.config import discover_config, load_config
from kaizenlint.executor import AsyncExecutor
from kaizenlint.files import resolve_files
from kaizenlint.models import (
    CheckTask,
    KaizenlintConfig,
    LintRule,
    LintSource,
    LintSourceName,
    LintViolation,
    SuppressionEntry,
)
from kaizenlint.rules import resolve_rules

app = typer.Typer(add_completion=False)


def _build_suppression_index(
    config: KaizenlintConfig,
) -> dict[tuple[str, str], SuppressionEntry]:
    index: dict[tuple[str, str], SuppressionEntry] = {}
    for file_path, entries in config.suppression.items():
        normalized = Path(file_path).as_posix()
        for entry in entries:
            index[(normalized, entry.rule)] = entry
    return index


def _build_tasks(
    resolved: list[Path],
    rules: list[LintRule],
    project_root: Path,
    suppression_index: dict[tuple[str, str], SuppressionEntry],
) -> tuple[list[CheckTask], dict[int, tuple[str, str]], set[tuple[str, str]]]:
    """タスクリストを構築し、task_keys と used_suppressions を返します。

    resolved の各 Path に対して read_text() / LintSource / LintSourceName を内部で構築します。
    """
    tasks: list[CheckTask] = []
    task_keys: dict[int, tuple[str, str]] = {}
    used_suppressions: set[tuple[str, str]] = set()

    for filepath in resolved:
        source = LintSource(content=filepath.read_text())
        source_name = LintSourceName(name=str(filepath))

        try:
            rel_file = filepath.relative_to(project_root).as_posix()
        except ValueError:
            rel_file = None

        for rule in rules:
            rule_key = f"{rule.source_path}:{rule.title}"
            lookup_key = (rel_file, rule_key) if rel_file else None

            if not rule.matches_file(filepath):
                if lookup_key and lookup_key in suppression_index:
                    used_suppressions.add(lookup_key)
                continue

            entry = suppression_index.get(lookup_key) if lookup_key else None

            if entry is not None:
                used_suppressions.add(lookup_key)  # type: ignore[arg-type]
                if entry.messages is None:
                    continue  # skip
                supplement = entry.messages
            else:
                supplement = []

            task = CheckTask(
                source=source,
                source_name=source_name,
                rule=rule,
                supplement_messages=supplement,
            )
            task_keys[id(task)] = (
                rel_file or str(filepath),
                rule_key,
            )
            tasks.append(task)

    return tasks, task_keys, used_suppressions


@app.callback(invoke_without_command=True)
def _callback(ctx: typer.Context) -> None:
    """サブコマンド未指定時にヘルプを表示します。"""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@app.command("check")
def check_cmd(
    files: Annotated[
        Optional[list[Path]],
        typer.Argument(help="対象ファイル / ディレクトリです。省略時はカレント ディレクトリを使います。"),
    ] = None,
    exclude: Annotated[
        Optional[list[str]],
        typer.Option("--exclude", help="config の exclude を上書きします。"),
    ] = None,
    extend_exclude: Annotated[
        Optional[list[str]],
        typer.Option("--extend-exclude", help="config の exclude に追加します。"),
    ] = None,
    force_exclude: Annotated[
        Optional[bool],
        typer.Option(help="明示ファイルにも exclude を適用します。"),
    ] = None,
    respect_gitignore: Annotated[
        Optional[bool],
        typer.Option(help=".gitignore を尊重します。"),
    ] = None,
    config_path: Annotated[
        Optional[Path],
        typer.Option("--config", help="config ファイル パスを指定します。"),
    ] = None,
) -> None:
    """kaizenlint でファイルをチェックします。

    Parameters
    ----------
    files: Optional[list[Path]]
        対象ファイル / ディレクトリです。省略時はカレント ディレクトリを使います。
    exclude: Optional[list[str]]
        config の exclude を上書きします。
    extend_exclude: Optional[list[str]]
        config の exclude に追加します。
    force_exclude: Optional[bool]
        明示ファイルにも exclude を適用します。
    respect_gitignore: Optional[bool]
        .gitignore を尊重するかを指定します。
    config_path: Optional[Path]
        config ファイル パスを指定します。

    Raises
    ------
    typer.Exit
        違反があれば exit code 1 で終了します。
    """
    if config_path is not None:
        config_file = config_path.resolve()
        config = load_config(config_file)
    else:
        config_file, config = discover_config()

    config_dir = config_file.parent

    if exclude is not None:
        config.exclude = exclude
    if extend_exclude is not None:
        config.extend_exclude = extend_exclude
    if force_exclude is not None:
        config.force_exclude = force_exclude
    if respect_gitignore is not None:
        config.respect_gitignore = respect_gitignore

    target_paths = files if files else [Path(".")]
    resolved = resolve_files(target_paths, config, config_dir)

    if not resolved:
        typer.echo("No files to check.")
        raise typer.Exit(0)

    rules = resolve_rules(config, config_dir)

    if not rules:
        typer.echo("No rules found.")
        raise typer.Exit(0)

    warned_patterns: set[tuple[str, str]] = set()
    for rule in rules:
        for pat in rule.applies_to:
            if ("/" in pat or "**" in pat) and (rule.source_path, pat) not in warned_patterns:
                warned_patterns.add((rule.source_path, pat))
                typer.echo(
                    f"Warning: applies_to パターン {pat!r} ({rule.source_path}) は"
                    " ファイル名のみでマッチされます。パス区切りや ** は無視されます。",
                    err=True,
                )

    typer.echo(f"Checking {len(resolved)} file(s) with {len(rules)} rule(s)...")

    project_root = config_dir.parent
    suppression_index = _build_suppression_index(config)

    tasks, task_keys, used_suppressions = _build_tasks(
        resolved, rules, project_root, suppression_index
    )

    # 未使用の suppression を警告します。
    for key in suppression_index:
        if key not in used_suppressions:
            typer.echo(
                f"Warning: 未使用の suppression: {key[0]} × {key[1]}", err=True
            )

    executor = AsyncExecutor()
    violations_for_tips: list[tuple[str, str]] = []

    def on_result(task: CheckTask, violation: LintViolation | None) -> None:
        """チェック結果を受け取り、違反があれば出力します。"""
        hint_label = " (hint適用中)" if task.supplement_messages else ""
        if violation is not None:
            typer.echo(
                f"{task.source_name.name}:  [{violation.rule.title}]{hint_label} {violation.message.text}"
            )
            tk = task_keys.get(id(task))
            if tk:
                violations_for_tips.append(tk)

    executor.execute(tasks, config, on_result)

    if violations_for_tips:
        typer.echo("\n--- Tips ---", err=True)
        typer.echo(
            "意図的な設計判断であれば messages で理由を記載してください。",
            err=True,
        )
        typer.echo(
            "LLM が理由を考慮して再判定します。それでも解決しない場合のみ skip を検討してください。",
            err=True,
        )
        by_file: dict[str, list[str]] = {}
        for rel_file_tip, rule_key_tip in violations_for_tips:
            by_file.setdefault(rel_file_tip, []).append(rule_key_tip)
        for file_path, rule_key_list in by_file.items():
            typer.echo("\n[suppression]", err=True)
            typer.echo(f'"{file_path}" = [', err=True)
            for rule_key in rule_key_list:
                typer.echo(
                    f'    {{ rule = "{rule_key}",'
                    ' messages = ["ここに理由を記載"] },',
                    err=True,
                )
            typer.echo("]", err=True)
        typer.echo(
            "\n# 完全にスキップする場合 (最終手段):",
            err=True,
        )
        typer.echo(
            '#   { rule = "...", messages = [...] } の代わりに'
            ' { rule = "..." } と書きます。',
            err=True,
        )
        raise typer.Exit(1)
