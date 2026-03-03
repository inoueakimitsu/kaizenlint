import tomllib
from pathlib import Path

from kaizenlint.models import KaizenlintConfig


def load_config(path: Path) -> KaizenlintConfig:
    """TOML を読み込み Pydantic でバリデーションした設定を返します。"""
    with path.open("rb") as config_file:
        data = tomllib.load(config_file)
    return KaizenlintConfig.model_validate(data)


def discover_config(start: Path | None = None) -> tuple[Path, KaizenlintConfig]:
    """CWD から親へ .kaizenlint/config.toml を探索します。見つからなければエラーになります。"""
    current = (start or Path.cwd()).resolve()

    # git や npm と同様に、CWD から親へ遡って設定ファイルを探索します。
    for directory in [current, *current.parents]:
        candidate = directory / ".kaizenlint" / "config.toml"
        if candidate.is_file():
            config = load_config(candidate)
            return candidate, config

    raise FileNotFoundError("kaizenlint config not found (.kaizenlint/config.toml)")
