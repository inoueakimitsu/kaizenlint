import tomllib
from pathlib import Path

from kaizenlint.models import KaizenlintConfig


def load_config(path: Path) -> KaizenlintConfig:
    with path.open("rb") as f:
        data = tomllib.load(f)
    return KaizenlintConfig.model_validate(data)


def discover_config(start: Path | None = None) -> tuple[Path, KaizenlintConfig]:
    """CWD から親へ .kaizenlint/config.toml を探索。見つからなければエラー。"""
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / ".kaizenlint" / "config.toml"
        if candidate.is_file():
            return candidate, load_config(candidate)
    raise FileNotFoundError("kaizenlint config not found (.kaizenlint/config.toml)")
