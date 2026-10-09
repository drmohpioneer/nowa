import json
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(hide_input_in_errors=True)

    database_url: str = ""
    demo_mode: bool | None = None
    server_secret: str = Field(default="", repr=False)
    link_secret: str = Field(default="", repr=False)
    public_base_url: str = ""
    trusted_proxy_hops: int | None = Field(default=None, ge=0)
    render_git_commit: str = "local"
    demo_doctor_password: str = Field(default="demo1234", repr=False)
    worker_in_process: int = Field(default=0, ge=0, le=1)
    port: int = Field(default=8000, ge=1, le=65535)
    telegram_bot_username: str = ""
    telegram_bot_token: str = Field(default="", repr=False)
    telegram_webhook_secret: str = Field(default="", repr=False)
    mapbox_token: str = Field(default="", repr=False)
    mapbox_timeout_s: float = Field(default=10, gt=0)
    demo_no_network: bool = False
    mapbox_usd_per_call: float = Field(default=0.002, ge=0)
    gemini_api_key: str = Field(default="", repr=False)
    openrouter_api_key: str = Field(default="", repr=False)
    ai_chain: str = (
        "gemini:gemini-3.8-flash,gemini:gemini-3.5-flash,openrouter:anthropic/claude-haiku-4.5"
    )
    judge_ai_msg_cap: int = Field(default=200, ge=0)
    judge_codes: str = Field(default="", repr=False)
    ai_daily_budget_usd: float = Field(default=10, ge=0)
    ai_clinic_daily_ceiling: int = Field(default=1000, ge=0)
    library_data_dir: Path = Path(__file__).parent / "library" / "data"
    library_min_score: float = Field(default=0.64, ge=-1, le=1)
    embedding_usd_per_call: float = Field(default=0.00001, ge=0)
    ai_rates_json: dict[str, dict[str, float]] = Field(default_factory=dict)

    agreement_party_company_name: str = ""
    agreement_party_company_address: str = ""
    agreement_party_commercial_register_number: str = ""
    agreement_party_privacy_email: str = ""
    agreement_party_dpo_name: str = ""
    agreement_party_render_region: str = ""
    agreement_party_backup_window_days: str = ""
    agreement_party_pilot_end_date: str = ""
    agreement_party_liability_cap_egp: str = ""
    agreement_party_notice_days: str = ""

    @field_validator("ai_chain")
    @classmethod
    def validate_ai_chain(cls, value: str) -> str:
        for entry in value.split(","):
            provider, separator, model = entry.strip().partition(":")
            if not separator or not model.strip() or provider not in {"gemini", "openrouter"}:
                raise ValueError(
                    "AI_CHAIN entries must be gemini:model or openrouter:model; "
                    "empty entries and unknown providers are not allowed"
                )
        return value

    @model_validator(mode="after")
    def configure(self) -> Self:
        if self.demo_mode is None:
            self.demo_mode = not bool(self.database_url)
        hosted = "RENDER" in os.environ
        if self.demo_mode and hosted:
            raise ValueError("DEMO_MODE is not allowed on a hosted deploy")
        if self.trusted_proxy_hops is None:
            self.trusted_proxy_hops = 1 if hosted else 0
        if not self.demo_mode:
            for name in ("SERVER_SECRET", "LINK_SECRET"):
                if len(getattr(self, name.lower()).encode()) < 32:
                    raise ValueError(f"{name} must be set and at least 32 bytes long")
            if not self.public_base_url:
                raise ValueError("PUBLIC_BASE_URL must be set")
            if (
                not self.database_url
                or make_url(self.database_url).get_backend_name() != "postgresql"
            ):
                raise ValueError("DATABASE_URL must use Postgres in production")
        elif not self.server_secret or not self.link_secret:
            self.load_demo_secrets()
        if not self.public_base_url:
            self.public_base_url = "http://127.0.0.1:8000"
        url = urlsplit(self.public_base_url)
        if url.scheme not in {"http", "https"} or not url.netloc or url.query or url.fragment:
            raise ValueError("PUBLIC_BASE_URL must be an absolute HTTP(S) base URL")
        self.public_base_url = self.public_base_url.rstrip("/")
        for rates in self.ai_rates_json.values():
            if set(rates) != {"in", "out"} or any(value < 0 for value in rates.values()):
                raise ValueError('AI_RATES_JSON rates must have nonnegative "in" and "out" values')
        return self

    def load_demo_secrets(self) -> None:
        database = make_url(self.database_url).database if self.database_url else "nowa-demo.db"
        path = Path(database or "nowa-demo.db").resolve().parent / ".nowa-secrets"
        if not path.exists():
            values = {name: secrets.token_urlsafe(32) for name in ("SERVER_SECRET", "LINK_SECRET")}
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "w") as stream:
                    json.dump(values, stream)
        values = json.loads(path.read_text())
        for name in ("SERVER_SECRET", "LINK_SECRET"):
            if not getattr(self, name.lower()):
                value = values.get(name)
                if not isinstance(value, str) or len(value.encode()) < 32:
                    raise ValueError(f"{name} is invalid in .nowa-secrets")
                setattr(self, name.lower(), value)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def secret_ok(name: str) -> bool:
    return len(os.environ.get(name, "").encode()) >= 32


def configure_demo_network() -> None:
    """The local demo opts out of outbound adapters before settings are cached."""
    os.environ.setdefault("DEMO_NO_NETWORK", "1")
    get_settings.cache_clear()
