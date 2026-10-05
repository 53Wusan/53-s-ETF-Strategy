from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"), extra="ignore", case_sensitive=False
    )

    app_env: str = "development"
    app_name: str = "杠杆 ETF 贪恐策略系统"
    database_url: str = "sqlite:///./leveraged_etf.db"
    admin_username: str = "53"
    admin_password: str = "change-me-now"
    admin_password_hash: str = ""
    jwt_secret: str = "development-only-secret-change-in-production"
    session_cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]
    base_currency: str = "CNY"
    public_base_url: str = "http://localhost:8000"
    feishu_webhook_url: str = ""
    feishu_webhook_secret: str = ""
    auto_fetch_market_data: bool = True
    market_data_lookback_years: int = 8
    data_stale_hours: int = 36
    backup_dir: Path = Path("/backups")
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "leveraged_etf"
    postgres_user: str = "leveraged_etf"
    postgres_password: str = ""

    @field_validator("database_url")
    @classmethod
    def resolve_database_url(cls, value: str) -> str:
        url = make_url(value)
        if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
            if url.query.get("uri") == "true":
                raise ValueError("SQLite URI mode is unsupported; use an ordinary file path")
            database = Path(url.database)
            if not database.is_absolute():
                database = BACKEND_DIR / database
            url = url.set(database=database.resolve().as_posix())
        return url.render_as_string(hide_password=False)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
