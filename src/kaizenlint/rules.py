import glob as globmod
from pathlib import Path
from typing import Annotated, cast

import frontmatter
from markdown_it import MarkdownIt
from pydantic import Field, TypeAdapter

from kaizenlint.models import (
    CheckerConfig,
    DEFAULT_CHECKER_CONFIG,
    KaizenlintConfig,
    LintRule,
)


def _parse_checker(
    metadata: dict[str, object],
) -> CheckerConfig:
    """frontmatter の metadata から checker 設定を解決します。

    discriminator="type" により LLM/regex 等の checker を自動判別します。
    """
    checker_raw = metadata.get("checker")
    if checker_raw is None:
        return DEFAULT_CHECKER_CONFIG
    adapter: TypeAdapter[CheckerConfig] = TypeAdapter(
        Annotated[CheckerConfig, Field(discriminator="type")]
    )
    return adapter.validate_python(checker_raw)


def parse_rule_file(path: Path, source_path: str = "") -> list[LintRule]:
    """ルール ファイルをパースしてルールのリストを返します。

    frontmatter の ``applies_to`` はファイル単位で定義され、
    同一ファイル内の全ルールに共有されます。
    """
    # frontmatter から checker 設定を取得し、本文をパースします。
    post = frontmatter.load(str(path))
    checker = _parse_checker(post.metadata)
    applies_to = cast(list[str], post.metadata.get("applies_to", []))
    body = post.content
    lines = body.splitlines()

    # H2 見出しをルールの区切りとして使うため、トークンから位置を収集します。
    md = MarkdownIt()
    tokens = md.parse(body)
    h2_positions = []
    for idx, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h2" and token.map:
            title_token = tokens[idx + 1]
            start_line = token.map[0]
            title = title_token.content
            h2_positions.append((start_line, title))

    # 各 H2 セクションの本文を description として LintRule を構築します。
    rules = []
    for i, (start_line, title) in enumerate(h2_positions):
        # 次の H2 の開始行まで、または末尾までを取得します
        end_line = h2_positions[i + 1][0] if i + 1 < len(h2_positions) else len(lines)
        # 見出し行自体をスキップして本文を取得します
        description = "\n".join(lines[start_line + 1 : end_line]).strip()
        rules.append(
            LintRule(
                title=title,
                description=description,
                checker=checker,
                source_path=source_path,
                applies_to=applies_to,
            )
        )

    return rules


def resolve_rules(
    config: KaizenlintConfig,
    config_dir: Path,
) -> list[LintRule]:
    """ルールファイルを探索してパースします。プロジェクトと個人ルールのハイブリッドです。"""
    rule_files: dict[Path, None] = {}

    # プロジェクトルール: config.rules の glob を config_dir 基準で解決します
    for pattern in config.rules:
        for match in sorted(globmod.glob(str(config_dir / pattern), recursive=True)):
            rule_files[Path(match).resolve()] = None

    # 個人ルール (~/.kaizenlint/rules/**/*.md) を探索します
    home_rules = Path.home() / ".kaizenlint" / "rules"
    if home_rules.is_dir():
        for match in sorted(
            globmod.glob(str(home_rules / "**" / "*.md"), recursive=True)
        ):
            rule_files[Path(match).resolve()] = None

    all_rules: list[LintRule] = []
    for rule_file in rule_files:
        # config_dir からの相対パスを計算します (個人ルールは絶対パス)
        try:
            sp = rule_file.relative_to(config_dir).as_posix()
        except ValueError:
            sp = str(rule_file)
        all_rules.extend(parse_rule_file(rule_file, source_path=sp))

    return all_rules
