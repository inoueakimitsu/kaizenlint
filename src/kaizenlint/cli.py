from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from kaizenlint.checker import check
from kaizenlint.config import discover_config, load_config
from kaizenlint.files import resolve_files
from kaizenlint.models import LintSource, LintSourceName
from kaizenlint.rules import resolve_rules

app = typer.Typer(add_completion=False)


@app.callback(invoke_without_command=True)
def _callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@app.command("check")
def check_cmd(
    files: Annotated[
        Optional[list[Path]],
        typer.Argument(help="対象ファイル/ディレクトリ。省略時 ."),
    ] = None,
    exclude: Annotated[
        Optional[list[str]],
        typer.Option("--exclude", help="config の exclude を上書き"),
    ] = None,
    extend_exclude: Annotated[
        Optional[list[str]],
        typer.Option("--extend-exclude", help="config の exclude に追加"),
    ] = None,
    force_exclude: Annotated[
        Optional[bool],
        typer.Option(help="明示ファイルにも exclude 適用"),
    ] = None,
    respect_gitignore: Annotated[
        Optional[bool],
        typer.Option(help=".gitignore を尊重"),
    ] = None,
    config_path: Annotated[
        Optional[Path],
        typer.Option("--config", help="config ファイルパス指定"),
    ] = None,
) -> None:
    """kaizenlint でファイルをチェックする。"""
    # 1. config ロード
    if config_path is not None:
        config_file = config_path.resolve()
        config = load_config(config_file)
    else:
        config_file, config = discover_config()

    config_dir = config_file.parent

    # 2. CLI オプションで config をオーバーライド
    if exclude is not None:
        config.exclude = exclude
    if extend_exclude is not None:
        config.extend_exclude = extend_exclude
    if force_exclude is not None:
        config.force_exclude = force_exclude
    if respect_gitignore is not None:
        config.respect_gitignore = respect_gitignore

    # 3. 対象ファイル解決
    target_paths = files if files else [Path(".")]
    resolved = resolve_files(target_paths, config, config_dir)

    if not resolved:
        typer.echo("No files to check.")
        raise typer.Exit(0)

    # 4. ルール解決
    rules = resolve_rules(config, config_dir)

    if not rules:
        typer.echo("No rules found.")
        raise typer.Exit(0)

    typer.echo(f"Checking {len(resolved)} file(s) with {len(rules)} rule(s)...")

    # 5. ファイルごとに check() を呼ぶ
    has_violations = False
    for filepath in resolved:
        source = LintSource(content=filepath.read_text())
        source_name = LintSourceName(name=str(filepath.name))
        violations = check(source, source_name, rules, config)
        for v in violations:
            has_violations = True
            typer.echo(f"{filepath}:  [{v.rule.title}] {v.message.text}")

    # 6. exit code
    if has_violations:
        raise typer.Exit(1)
