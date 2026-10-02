"""Settings, read from environment variables (the app.env file on the server)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GT_", env_file=None, extra="ignore")

    # Core
    database_url: str = "sqlite:///./gandytrade.db"
    secret_key: str = "change-me"
    # Cookies are HTTPS-only in production. Set GT_COOKIE_SECURE=false only for local testing.
    cookie_secure: bool = True
    # A session ends after this long in total, or after this long with no activity from you
    # (automatic chart refreshes don't count as activity).
    session_hours: int = 12
    session_idle_minutes: int = 30

    # Shared secret that Apache adds to every request it passes on. When set, any request
    # without it (e.g. another program on the server calling the port directly) is refused.
    proxy_secret: str = ""

    # Sign-in protection
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # Read-only market data. When a key is missing, clearly labelled sample data is used.
    oanda_token: str = ""
    twelvedata_key: str = ""
    # London shares (daily/weekly/monthly) from Alpha Vantage's free plan.
    alphavantage_key: str = ""

    # Off-server backups to a Backblaze B2 bucket (S3-compatible endpoint, e.g. s3.eu-central-003.backblazeb2.com).
    # The key should be limited to that one bucket, with write-only access. Backups are encrypted with the
    # passphrase before they leave the server; without the passphrase they can't be restored, so keep a copy.
    backup_endpoint: str = ""
    backup_bucket: str = ""
    backup_key_id: str = ""
    backup_key: str = ""
    backup_passphrase: str = ""

    # Where the built frontend lives inside the container.
    frontend_dir: str = "/app/frontend"


@lru_cache
def get_settings() -> Settings:
    return Settings()
