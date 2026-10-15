"""Settings for the boost-integrated-unit (升压一体机) product, independent of the cabinet ones."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..config import REPOSITORY_ROOT, get_settings

PRODUCT_KEY = "boost-integrated-unit"


class BoostSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPOSITORY_ROOT / ".env"), env_prefix="SOP_BOOST_", extra="ignore")

    template_dir: Path = REPOSITORY_ROOT / "templates" / PRODUCT_KEY / "v1"
    max_source_file_bytes: int = 30 * 1024 * 1024
    max_images: int = 150

    @property
    def data_dir(self) -> Path:
        return get_settings().data_root / "boost"

    @property
    def sources_dir(self) -> Path:
        return self.data_dir / "sources"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "temp"

    @property
    def master(self) -> Path:
        return self.template_dir / "master.docx"


@lru_cache
def get_boost_settings() -> BoostSettings:
    return BoostSettings()


@lru_cache
def _load_manifest(path: str, mtime_ns: int) -> dict:
    del mtime_ns
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_manifest(directory: Path) -> dict:
    path = directory / "manifest.yaml"
    return _load_manifest(str(path), path.stat().st_mtime_ns)
