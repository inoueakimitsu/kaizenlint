from pathlib import Path

import pathspec

from kaizenlint.models import KaizenlintConfig


def _load_gitignore(directory: Path) -> pathspec.PathSpec:
    """directory 内の .gitignore を読み込んで PathSpec を返します。"""
    gitignore = directory / ".gitignore"
    if gitignore.is_file():
        return pathspec.PathSpec.from_lines(
            "gitwildmatch", gitignore.read_text().splitlines()
        )
    return pathspec.PathSpec.from_lines("gitwildmatch", [])


def _is_excluded(
    path: Path,
    base: Path,
    exclude_spec: pathspec.PathSpec,
    gitignore_spec: pathspec.PathSpec,
    respect_gitignore: bool,
) -> bool:
    """path が exclude または gitignore にマッチするか判定します。"""
    try:
        rel = path.relative_to(base)
    except ValueError:
        rel = path

    rel_str = str(rel)

    # .venv 等のパターンがディレクトリ階層のどの深さでも効くようにするため、
    # パス コンポーネント単位でも exclude を照合します。
    for part in rel.parts:
        if exclude_spec.match_file(part):
            return True
    if exclude_spec.match_file(rel_str):
        return True

    if respect_gitignore and gitignore_spec.match_file(rel_str):
        return True

    return False


def resolve_files(
    paths: list[Path],
    config: KaizenlintConfig,
    config_dir: Path,
) -> list[Path]:
    """対象ファイルを解決します。ディレクトリは再帰走査し、ファイルはそのまま返します。"""
    project_root = config_dir.parent
    include_spec = pathspec.PathSpec.from_lines("gitwildmatch", config.include)
    all_excludes = config.exclude + config.extend_exclude
    exclude_spec = pathspec.PathSpec.from_lines("gitwildmatch", all_excludes)
    gitignore_spec = (
        _load_gitignore(project_root)
        if config.respect_gitignore
        else pathspec.PathSpec.from_lines("gitwildmatch", [])
    )

    resolved: list[Path] = []

    for target in paths:
        target = target.resolve()
        if target.is_file():
            if config.force_exclude and _is_excluded(
                target,
                project_root,
                exclude_spec,
                gitignore_spec,
                config.respect_gitignore,
            ):
                continue
            resolved.append(target)
        elif target.is_dir():
            for child in sorted(target.rglob("*")):
                if not child.is_file():
                    continue
                if _is_excluded(
                    child,
                    project_root,
                    exclude_spec,
                    gitignore_spec,
                    config.respect_gitignore,
                ):
                    continue
                try:
                    rel = child.relative_to(project_root)
                except ValueError:
                    rel = child
                if include_spec.match_file(rel.name):
                    resolved.append(child)

    return resolved
