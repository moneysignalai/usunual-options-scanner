import logging
import os
from typing import List, Optional

from dotenv import load_dotenv
from pydantic.v1 import BaseSettings, Field, validator


class Settings(BaseSettings):
    """
    Application settings.

    Values are loaded from environment variables (Render dashboard, .env, etc.).
    """

    # === Massive API ===
    massive_api_key: str = Field(..., env="MASSIVE_API_KEY")
    massive_base_url: str = Field("https://api.massive.app", env="MASSIVE_BASE_URL")

    # === Core scanner settings ===
    enable_telegram: bool = Field(False, env="ENABLE_TELEGRAM")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    scan_interval_seconds: int = Field(60, env="SCAN_INTERVAL_SECONDS")

    # === Telegram ===
    telegram_bot_token: Optional[str] = Field(None, env="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(None, env="TELEGRAM_CHAT_ID")

    # === Universe & unusual options filters ===
    # e.g. "SPY,QQQ,IWM,NVDA,TSLA,AAPL,MSFT,AMZN,META,AVGO,AMD"
    ticker_universe: List[str] = Field(
        ["SPY", "QQQ", "IWM"],
        env="TICKER_UNIVERSE",
        description="Comma-separated list of tickers to scan",
    )

    # DTE filter (in days)
    unusual_max_dte_days: int = Field(45, env="UNUSUAL_MAX_DTE_DAYS")
    unusual_min_dte_days: int = Field(0, env="UNUSUAL_MIN_DTE_DAYS")

    # Notional size filter (in dollars)
    unusual_min_notional: float = Field(250_000.0, env="UNUSUAL_MIN_NOTIONAL")

    # Volume / OI ratio filter
    unusual_min_volume_oi_ratio: float = Field(
        1.0, env="UNUSUAL_MIN_VOLUME_OI_RATIO"
    )

    # --- Validators ---------------------------------------------------------

    @validator("ticker_universe", pre=True)
    def parse_ticker_universe(cls, v):
        """
        Accept either a comma-separated string or a list and normalize to
        upper-case tickers.
        """
        if isinstance(v, str):
            return [t.strip().upper() for t in v.split(",") if t.strip()]
        return v

    @validator("log_level", pre=True)
    def normalize_log_level(cls, v):
        if not v:
            return "INFO"
        return str(v).upper()

    @validator("massive_api_key")
    def ensure_massive_api_key(cls, v):
        if not v or not v.strip():
            # This will surface as a nice validation error instead of a
            # confusing "Illegal header value b'Bearer '" later.
            raise ValueError(
                "MASSIVE_API_KEY is not set. Please configure it "
                "in your Render environment variables."
            )
        return v.strip()

    class Config:
        # Optional: if you run locally with a .env file
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


def load_settings() -> Settings:
    """
    Load settings from environment variables.

    - On Render: uses the env vars you configured in the dashboard.
    - Locally: also reads from a .env file if present.
    """
    # This is harmless on Render; if there is no .env file, nothing happens.
    load_dotenv()

    settings = Settings()  # BaseSettings will pull from the environment

    # Small startup log so you can see what it loaded (without secrets)
    logging.getLogger("config").info(
        "Config loaded | tickers=%s | interval=%ss | telegram=%s",
        ",".join(settings.ticker_universe),
        settings.scan_interval_seconds,
        settings.enable_telegram,
    )

    return settings
