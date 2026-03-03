"""kaizenlint の CLI エントリー ポイントを提供します。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from kaizenlint.config import discover_config, load_config
from kaizenlint.executor import AsyncExecutor
from kaizenlint.files import resolve_files
from kaizenlint.models import CheckTask, LintSource, LintSourceName, LintViolation
from kaizenlint.rules import resolve_rules

app = typer.Typer(add_completion=False)


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
        typer.Argument(help="対象ファイル / ディレクトリーです。省略時はカレント ディレクトリーを使います。"),
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
        対象ファイル / ディレクトリーです。省略時はカレント ディレクトリーを使います。
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

    typer.echo(f"Checking {len(resolved)} file(s) with {len(rules)} rule(s)...")

    tasks: list[CheckTask] = []
    for filepath in resolved:
        source = LintSource(content=filepath.read_text())
        source_name = LintSourceName(name=str(filepath))
        for rule in rules:
            tasks.append(CheckTask(source=source, source_name=source_name, rule=rule))

    executor = AsyncExecutor()
    has_violations = False

    def on_result(task: CheckTask, violation: LintViolation | None) -> None:
        """チェック結果を受け取り、違反があれば出力します。"""
        nonlocal has_violations
        if violation is not None:
            has_violations = True
            typer.echo(
                f"{task.source_name.name}:  [{violation.rule.title}] {violation.message.text}"
            )

    executor.execute(tasks, config, on_result)

    if has_violations:
        raise typer.Exit(1)
