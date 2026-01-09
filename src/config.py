from __future__ import annotations

import os
from typing import List

from dotenv import load_dotenv
from pydantic.v1 import BaseModel, Field, validator


class Settings(BaseModel):
    massive_api_key: str = Field(..., env="MASSIVE_API_KEY")

    # We now hard-code the Massive base URL in code and do NOT read it from env.
    # This avoids issues like accidentally ending up with `/v1/v3/...` in the URL.
    massive_base_url: str = Field("https://api.massive.app")

    # ... other fields (ticker_universe, scan_interval_seconds, etc.) stay the same ...

    @validator("massive_api_key")
    def validate_massive_api_key(cls, v: str) -> str:
        """Ensure the API key is not empty or whitespace-only."""
        if not v or not v.strip():
            raise ValueError("MASSIVE_API_KEY is set but empty or whitespace. Please set a real key.")
        return v.strip()

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
