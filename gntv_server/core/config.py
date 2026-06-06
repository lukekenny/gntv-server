from functools import lru_cache

from pydantic import AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "gntv-server"
    database_url: str = Field(
        default="postgresql+asyncpg://gntv:gntv@localhost:5432/gntv",
        validation_alias="DATABASE_URL",
    )
    admin_token: str = Field(default="", validation_alias="ADMIN_TOKEN")
    unifi_base_url: str = Field(
        default="https://172.16.0.1/proxy/network",
        validation_alias="UNIFI_BASE_URL",
    )
    unifi_site: str = Field(default="default", validation_alias="UNIFI_SITE")
    unifi_api_key: str = Field(default="", validation_alias="UNIFI_API_KEY")
    unifi_verify_tls: bool = Field(default=False, validation_alias="UNIFI_VERIFY_TLS")
    public_base_url: AnyUrl = Field(
        default="http://localhost:8000",
        validation_alias="PUBLIC_BASE_URL",
    )
    trust_proxy_headers: bool = Field(
        default=False,
        validation_alias="TRUST_PROXY_HEADERS",
    )
    trusted_proxy_cidrs: str = Field(
        default="",
        validation_alias="TRUSTED_PROXY_CIDRS",
    )
    guest_pin_max_attempts: int = Field(
        default=5,
        ge=1,
        validation_alias="GUEST_PIN_MAX_ATTEMPTS",
    )
    guest_pin_window_seconds: int = Field(
        default=300,
        ge=1,
        validation_alias="GUEST_PIN_WINDOW_SECONDS",
    )
    guest_session_duration_seconds: int = Field(
        default=14_400,
        ge=300,
        validation_alias="GUEST_SESSION_DURATION_SECONDS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
