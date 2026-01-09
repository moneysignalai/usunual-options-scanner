from __future__ import annotations

import os
from typing import List

from dotenv import load_dotenv
from pydantic.v1 import BaseModel, Field, validator


class Settings(BaseModel):
    """
    Central configuration for the unusual options scanner.

    Notes:
    - We hard-code the Massive base URL here instead of reading it from ENV to avoid
      accidentally ending up with bad values like `https://api.massive.app/v1/v3/...`.
    - The only required env var is MASSIVE_API_KEY. Everything else has sane defaults.
    """

    # Massive / market-data config
    massive_api_key: str = Field("", env="MASSIVE_API_KEY")
    massive_base_url: str = "https://api.massive.com"

    # Scanner config
    ticker_universe: List[str] = Field(
        default_factory=lambda: [
            "SPY",
            "QQQ",
            "IWM",
            "NVDA",
            "TSLA",
            "AAPL",
            "MSFT",
            "AMZN",
            "META",
            "AVGO",
            "AMD",
        ],
        env="TICKER_UNIVERSE",
    )
    scan_interval_seconds: int = Field(60, env="SCAN_INTERVAL_SECONDS")

    # Unusual-options filters
    unusual_min_notional: float = Field(25_000.0, env="UNUSUAL_MIN_NOTIONAL")
    unusual_min_volume_oi_ratio: float = Field(1.0, env="UNUSUAL_MIN_VOLUME_OI_RATIO")
    unusual_min_dte_days: int = Field(0, env="UNUSUAL_MIN_DTE_DAYS")
    unusual_max_dte_days: int = Field(21, env="UNUSUAL_MAX_DTE_DAYS")

    # Logging
    log_level: str = Field("INFO", env="LOG_LEVEL")

    # Telegram
    enable_telegram: bool = Field(False, env="ENABLE_TELEGRAM")
    telegram_bot_token: str = Field("", env="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field("", env="TELEGRAM_CHAT_ID")

    @validator("ticker_universe", pre=True)
    def _parse_ticker_universe(cls, v: object) -> List[str]:
        """
        Allow both:
          - a comma-separated string: "SPY,QQQ,NVDA"
          - a proper list: ["SPY", "QQQ", "NVDA"]
        """
        if isinstance(v, list):
            return [s.strip().upper() for s in v if isinstance(s, str) and s.strip()]
        if isinstance(v, str):
            return [s.strip().upper() for s in v.split(",") if s.strip()]
        raise TypeError("ticker_universe must be a list or comma-separated string")

    @validator("enable_telegram", pre=True)
    def _parse_bool(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in {"1", "true", "yes", "y", "on"}
        return bool(v)

    class Config:
        # Allow env-based population for fields with `env=` configured.
        env_file = ".env"
        env_file_encoding = "utf-8"


def load_settings() -> Settings:
    """
    Load Settings once per process.

    This is the single entry-point the rest of the app should use.
    """
    # Make sure .env (if present) is loaded before Pydantic reads env vars.
    load_dotenv()

    settings = Settings()  # Pydantic will read from environment automatically

    # Explicit sanity log to make debugging easier (logger set up later).
    # We avoid printing secrets.
    print(
        "Config loaded | tickers=%s | interval=%ss | telegram=%s"
        % (",".join(settings.ticker_universe), settings.scan_interval_seconds, settings.enable_telegram)
    )

    return settings
