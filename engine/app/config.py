"""Engine settings, read from environment variables set by the Electron main process."""

import os
from dataclasses import dataclass
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ENGINE_DIR.parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    token: str | None
    bin_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "clipping.db"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("CLIP_DATA_DIR", PROJECT_ROOT / ".data"))
    bin_dir = Path(os.environ.get("CLIP_BIN_DIR", PROJECT_ROOT / "bin"))
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "projects").mkdir(exist_ok=True)
    return Settings(
        data_dir=data_dir,
        # When unset (e.g. running the engine standalone for development) auth is disabled.
        token=os.environ.get("CLIP_ENGINE_TOKEN") or None,
        bin_dir=bin_dir,
    )
