"""Validated server configuration; credentials never appear in repr or errors."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env", extra="ignore", case_sensitive=False,
        hide_input_in_errors=True,
    )
    app_name: str = "Scanner API"
    app_env: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api"
    allowed_origins: str = "http://localhost:3000,http://localhost:5173"
    supabase_url: str = ""
    supabase_publishable_key: SecretStr = SecretStr("")
    supabase_secret_key: SecretStr = SecretStr("")
    supabase_anon_key: SecretStr = SecretStr("")
    supabase_service_role_key: SecretStr = SecretStr("")
    supabase_jwt_audience: str = "authenticated"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-5-mini"
    max_pdf_bytes: int = Field(default=26_214_400, ge=1024, le=26_214_400)
    max_pdf_pages: int = Field(default=100, ge=1, le=500)
    max_text_chars: int = Field(default=1_000_000, ge=1000, le=2_000_000)
    max_ocr_pages: int = Field(default=12, ge=0, le=50)
    max_context_chars: int = Field(default=60_000, ge=4000, le=120_000)
    pdf_timeout_seconds: int = Field(default=45, ge=5, le=120)
    request_timeout_seconds: int = Field(default=75, ge=5, le=90)
    requests_per_minute: int = Field(default=30, ge=1, le=300)
    processing_concurrency: int = Field(default=2, ge=1, le=4)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("api_prefix")
    @classmethod
    def valid_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/") or "?" in value:
            raise ValueError("API_PREFIX must start with / and have no trailing slash")
        return value

    @field_validator("supabase_url")
    @classmethod
    def valid_supabase_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value or "YOUR_PROJECT" in value:
            return ""
        parsed = urlsplit(value)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query
                or parsed.fragment or parsed.path or
                (parsed.scheme != "https" and not (local and parsed.scheme == "http"))):
            raise ValueError("SUPABASE_URL must be an HTTPS origin (HTTP only for localhost)")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def valid_origins(cls, value: str) -> str:
        for origin in value.split(","):
            if not origin.strip():
                continue
            parsed = urlsplit(origin.strip())
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username or parsed.password or parsed.path
                    or parsed.query or parsed.fragment):
                raise ValueError("ALLOWED_ORIGINS must contain explicit HTTP(S) origins")
        return value

    @property
    def origins(self) -> list[str]:
        return [v.strip() for v in self.allowed_origins.split(",") if v.strip()]

    @staticmethod
    def usable(secret: SecretStr) -> bool:
        value = secret.get_secret_value()
        return bool(value) and not value.startswith(("YOUR_", "your_", "replace_"))

    @property
    def public_key(self) -> str:
        key = self.supabase_publishable_key
        return (key if self.usable(key) else self.supabase_anon_key).get_secret_value()

    @property
    def server_key(self) -> str:
        key = self.supabase_secret_key
        return (key if self.usable(key) else self.supabase_service_role_key).get_secret_value()

    @property
    def supabase_ready(self) -> bool:
        return bool(self.supabase_url) and all(
            self.usable(SecretStr(key)) for key in (self.public_key, self.server_key)
        )

    @property
    def ai_ready(self) -> bool:
        return self.usable(self.openai_api_key)
