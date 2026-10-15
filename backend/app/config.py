from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPOSITORY_ROOT / ".env"),
        env_prefix="SOP_",
        extra="ignore",
    )

    env: str = "development"
    database_url: str = f"sqlite:///{(REPOSITORY_ROOT / 'runtime' / 'sop-igs.db').as_posix()}"
    data_root: Path = REPOSITORY_ROOT / "runtime"
    secret_key: str = "development-only-change-me"
    session_cookie_secure: bool = False
    session_ttl_hours: int = 24
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin-change-me"
    word_com_enabled: bool = False
    word_com_timeout_seconds: int = 300
    display_timezone: str = "Asia/Shanghai"
    worker_poll_seconds: float = 2.0
    max_photo_bytes: int = 30 * 1024 * 1024
    max_project_photos: int = 200
    max_image_pixels: int = 100_000_000
    minimum_free_disk_gb: float = 5.0
    llm_base_url: str | None = None
    llm_api_key: str | None = Field(default=None, repr=False)
    llm_model: str | None = None
    llm_timeout_seconds: float = 10.0
    template_dir: Path = REPOSITORY_ROOT / "templates" / "liquid-cooled-cabinet" / "v1"
    public_base_url: str | None = None
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = Field(default=None, repr=False)
    feishu_admin_open_ids: str = ""
    feishu_timeout_seconds: float = 10.0

    @model_validator(mode="after")
    def reject_insecure_production_defaults(self) -> Settings:
        plain_http = (self.public_base_url or "").startswith("http://")
        if self.env == "production" and (
            self.secret_key == "development-only-change-me"
            or self.bootstrap_admin_password == "admin-change-me"
            or (not self.session_cookie_secure and not plain_http)
        ):
            raise ValueError(
                "Production requires a unique secret, admin password, and secure cookies "
                "(or an explicit http:// SOP_PUBLIC_BASE_URL for plain-HTTP intranet access)"
            )
        if plain_http and self.session_cookie_secure:
            raise ValueError("SOP_SESSION_COOKIE_SECURE must be false for an http:// public URL")
        return self

    @property
    def feishu_enabled(self) -> bool:
        return bool(self.feishu_app_id and self.feishu_app_secret)

    @property
    def feishu_admin_open_id_set(self) -> set[str]:
        return {item.strip() for item in self.feishu_admin_open_ids.split(",") if item.strip()}

    @property
    def originals_dir(self) -> Path:
        return self.data_root / "originals"

    @property
    def processed_dir(self) -> Path:
        return self.data_root / "processed"

    @property
    def outputs_dir(self) -> Path:
        return self.data_root / "outputs"

    @property
    def temp_dir(self) -> Path:
        return self.data_root / "temp"


@lru_cache
def get_settings() -> Settings:
    return Settings()
