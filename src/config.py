import os
from typing import Any, List, Optional

from dotenv import load_dotenv
from pydantic.v1 import BaseSettings, Field, validator


class Settings(BaseSettings):
    """
    Central application configuration.

    Values come from (in order of precedence):
      1) Environment variables set in Render's dashboard
      2) A local .env file (for local development)
      3) The defaults defined below
    """

    # --- Logging / general ---
    log_level: str = Field("INFO", env="LOG_LEVEL")

    # --- Massive API ---
    # Not required at the Pydantic level so the app doesn't crash if it's missing.
    # We'll warn loudly in load_settings() if it's empty.
    massive_api_key: str = Field("", env="MASSIVE_API_KEY")
    massive_base_url: str = Field(
        "https://api.massive.com",
        env="MASSIVE_BASE_URL",
    )

    # --- Scanner behaviour ---
    scan_interval_seconds: int = Field(60, env="SCAN_INTERVAL_SECONDS")

    # --- Telegram ---
    enable_telegram: bool = Field(False, env="ENABLE_TELEGRAM")
    telegram_bot_token: Optional[str] = Field(None, env="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(None, env="TELEGRAM_CHAT_ID")

    # --- Universe ---
    # We accept either:
    #   - JSON array: '["SPY","QQQ"]'
    #   - Comma / whitespace separated string: "SPY,QQQ IWM"
    ticker_universe: List[str] = Field(
        default_factory=lambda: ["SPY", "QQQ", "IWM"],
        env="TICKER_UNIVERSE",
    )

    # --- Unusual options filters ---
    unusual_max_dte_days: int = Field(30, env="UNUSUAL_MAX_DTE_DAYS")
    unusual_min_dte_days: int = Field(1, env="UNUSUAL_MIN_DTE_DAYS")
    unusual_min_notional: float = Field(100000.0, env="UNUSUAL_MIN_NOTIONAL")
    unusual_min_volume_oi_ratio: float = Field(1.0, env="UNUSUAL_MIN_VOLUME_OI_RATIO")

    # ---------- Validators ----------

    @validator("ticker_universe", pre=True)
    def parse_ticker_universe(cls, v: Any) -> List[str]:
        """
        Allow TICKER_UNIVERSE to be:
          - a JSON array
          - or "SPY,QQQ,NVDA TSLA" style string
        """
        if v is None or v == "":
            return ["SPY", "QQQ", "IWM"]

        # Already a list (e.g. from JSON)
        if isinstance(v, list):
            return [str(x).strip().upper() for x in v if str(x).strip()]

        # String from env
        if isinstance(v, str):
            parts: List[str] = []
            # Replace commas with spaces, then split on whitespace
            for token in v.replace(",", " ").split():
                token = token.strip().upper()
                if token:
                    parts.append(token)
            return parts or ["SPY", "QQQ", "IWM"]

        # Fallback
        return ["SPY", "QQQ", "IWM"]

    @validator("enable_telegram", pre=True)
    def parse_enable_telegram(cls, v: Any) -> bool:
        """
        Render will give us strings for booleans; normalize them.
        """
        if isinstance(v, bool):
            return v
        if v is None:
            return False
        if isinstance(v, str):
            return v.strip().lower() in {"1", "true", "yes", "on"}
        return bool(v)

    class Config:
        # We use the env names exactly as defined in Render (no prefix)
        env_prefix = ""
        case_sensitive = False

        # IMPORTANT:
        # By default BaseSettings tries to JSON-decode env vars for complex types.
        # That breaks when TICKER_UNIVERSE="SPY,QQQ,..." (not valid JSON).
        # We override json_loads to just return the raw string, and handle parsing
        # ourselves in the validators.
        json_loads = staticmethod(lambda v: v)


def load_settings() -> Settings:
    """
    Entry point used by worker.py to get a fully-populated Settings object.
    """
    # Local dev: load .env if present; on Render this does nothing.
    load_dotenv()

    settings = Settings()

    if not settings.massive_api_key:
        # This won't leak the key, just warns it's empty.
        print("WARNING: MASSIVE_API_KEY is empty – Massive API calls will fail.")

    print(
        "Config loaded | tickers=%s | interval=%ss | telegram=%s"
        % (
            ",".join(settings.ticker_universe),
            settings.scan_interval_seconds,
            settings.enable_telegram,
        )
    )
    return settings
