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
    unusual_min_notional: float = Field(25000.0, env="UNUSUAL_MIN_NOTIONAL")
    unusual_min_volume_oi_ratio: float = Field(1.0, env="UNUSUAL_MIN_VOLUME_OI_RATIO")
    unusual_min_dte_days: int = Field(0, env="UNUSUAL_MIN_DTE_DAYS")
    unusual_max_dte_days: int = Field(21, env="UNUSUAL_MAX_DTE_DAYS")
    log_level: str = Field("INFO", env="LOG_LEVEL")

    enable_telegram: bool = Field(False, env="ENABLE_TELEGRAM")
    telegram_bot_token: str = Field("", env="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field("", env="TELEGRAM_CHAT_ID")

    @validator("ticker_universe", pre=True)
    def parse_tickers(cls, value: object) -> List[str]:
        if isinstance(value, str):
            tickers = [item.strip().upper() for item in value.split(",") if item.strip()]
            return tickers
        if isinstance(value, list):
            return [str(item).strip().upper() for item in value if str(item).strip()]
        return []

    @validator("enable_telegram", pre=True)
    def parse_bool(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def load_settings() -> Settings:
    """
    Load settings from environment variables with sensible defaults.

    NOTE:
    - We no longer read MASSIVE_BASE_URL from the environment.
      The Massive base URL is fixed as https://api.massive.app in the Settings
      to prevent path/version bugs.
    """
    load_dotenv()
    return Settings(
        massive_api_key=os.getenv("MASSIVE_API_KEY", ""),
        # massive_base_url is NOT passed here; it uses the hard-coded default.
        ticker_universe=os.getenv(
            "TICKER_UNIVERSE",
            "SPY,QQQ,IWM,NVDA,TSLA,AAPL,MSFT,AMZN,META,AVGO,AMD",
        ),
        scan_interval_seconds=os.getenv("SCAN_INTERVAL_SECONDS", "60"),
        unusual_min_notional=os.getenv("UNUSUAL_MIN_NOTIONAL", "25000"),
        unusual_min_volume_oi_ratio=os.getenv("UNUSUAL_MIN_VOLUME_OI_RATIO", "1.0"),
        unusual_min_dte_days=os.getenv("UNUSUAL_MIN_DTE_DAYS", "0"),
        unusual_max_dte_days=os.getenv("UNUSUAL_MAX_DTE_DAYS", "21"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        enable_telegram=os.getenv("ENABLE_TELEGRAM", "false"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )
