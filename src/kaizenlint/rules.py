import glob as globmod
from pathlib import Path
from typing import Annotated

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
    """frontmatter の metadata から checker 設定を解決する。"""
    checker_raw = metadata.get("checker")
    if checker_raw is None:
        return DEFAULT_CHECKER_CONFIG
    adapter: TypeAdapter[CheckerConfig] = TypeAdapter(
        Annotated[CheckerConfig, Field(discriminator="type")]
    )
    return adapter.validate_python(checker_raw)


def parse_rule_file(path: Path) -> list[LintRule]:
    """ルールファイルをパースしてルールのリストを返す。"""
    post = frontmatter.load(str(path))
    checker = _parse_checker(post.metadata)
    body = post.content
    lines = body.split("\n")

    md = MarkdownIt()
    tokens = md.parse(body)

    # H2 見出しの開始行を収集
    h2_positions = []
    for token in tokens:
        if token.type == "heading_open" and token.tag == "h2" and token.map:
            title_token = tokens[tokens.index(token) + 1]
            h2_positions.append((token.map[0], title_token.content))

    rules = []
    for i, (start_line, title) in enumerate(h2_positions):
        # 次の H2 の開始行まで、または末尾まで
        end_line = h2_positions[i + 1][0] if i + 1 < len(h2_positions) else len(lines)
        # 見出し行自体をスキップして本文を取得
        description = "\n".join(lines[start_line + 1 : end_line]).strip()
        rules.append(LintRule(title=title, description=description, checker=checker))

    return rules


def resolve_rules(
    config: KaizenlintConfig,
    config_dir: Path,
) -> list[LintRule]:
    """ルールファイルを探索してパースする。プロジェクト + 個人ルールのハイブリッド。"""
    rule_files: dict[Path, None] = {}

    # プロジェクトルール: config.rules の glob を config_dir 基準で解決
    for pattern in config.rules:
        for match in sorted(globmod.glob(str(config_dir / pattern), recursive=True)):
            rule_files[Path(match).resolve()] = None

    # 個人ルール: ~/.kaizenlint/rules/**/*.md
    home_rules = Path.home() / ".kaizenlint" / "rules"
    if home_rules.is_dir():
        for match in sorted(globmod.glob(str(home_rules / "**" / "*.md"), recursive=True)):
            rule_files[Path(match).resolve()] = None

    all_rules: list[LintRule] = []
    for rule_file in rule_files:
        all_rules.extend(parse_rule_file(rule_file))

    return all_rules
