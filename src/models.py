from __future__ import annotations

from datetime import date
from typing import List, Optional, Any, Dict

from pydantic.v1 import BaseModel, Field, root_validator


def _get_nested(values: Dict[str, Any], key: str) -> Any:
    if "." not in key:
        return values.get(key)
    current: Any = values
    for part in key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


class UnderlyingAsset(BaseModel):
    symbol: Optional[str] = None
    ticker: Optional[str] = None
    name: Optional[str] = None
    exchange: Optional[str] = None
    type: Optional[str] = None
    price: Optional[float] = None

    class Config:
        extra = "ignore"


class OptionContractSnapshot(BaseModel):
    options_ticker: Optional[str] = None
    underlying_ticker: Optional[str] = None
    expiration_date: Optional[date] = None
    strike: Optional[float] = None
    contract_type: Optional[str] = None
    last_price: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    sweep: Optional[bool] = None
    trade_count: Optional[int] = None
    trade_size: Optional[int] = None
    notional: Optional[float] = None
    rvol: Optional[float] = None
    iv_percentile: Optional[float] = None
    unusual_score: Optional[float] = None
    underlying_price: Optional[float] = None

    @root_validator(pre=True)
    def normalize_fields(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(values, dict):
            return values

        def _first(*keys: str) -> Any:
            for key in keys:
                value = _get_nested(values, key)
                if value is not None:
                    return value
            return None

        if values.get("options_ticker") is None:
            values["options_ticker"] = _first(
                "symbol",
                "ticker",
                "options_ticker",
                "contract_symbol",
                "details.symbol",
                "option.symbol",
            )

        if values.get("underlying_ticker") is None:
            values["underlying_ticker"] = _first(
                "underlying_symbol",
                "underlying_ticker",
                "underlying.symbol",
                "underlying.ticker",
                "underlying_asset.symbol",
            )

        if values.get("expiration_date") is None:
            values["expiration_date"] = _first(
                "expiration",
                "expiration_date",
                "exp_date",
                "expiry",
                "details.expiration_date",
                "details.expiration",
                "contract.expiration_date",
            )

        if values.get("strike") is None:
            values["strike"] = _first(
                "strike",
                "strike_price",
                "details.strike_price",
                "contract.strike_price",
            )

        if values.get("last_price") is None:
            values["last_price"] = _first(
                "last",
                "last_price",
                "last_trade_price",
                "mark",
                "mid",
                "quote.last",
                "quote.last_price",
                "day.last",
            )

        if values.get("bid") is None:
            values["bid"] = _first(
                "bid",
                "bid_price",
                "best_bid",
                "quote.bid",
                "quote.bid_price",
            )

        if values.get("ask") is None:
            values["ask"] = _first(
                "ask",
                "ask_price",
                "best_ask",
                "quote.ask",
                "quote.ask_price",
            )

        if values.get("contract_type") is None:
            values["contract_type"] = _first(
                "contract_type",
                "option_type",
                "type",
                "right",
                "details.contract_type",
                "details.type",
                "contract.type",
            )

        if values.get("open_interest") is None:
            values["open_interest"] = _first(
                "oi",
                "open_interest",
                "openInterest",
                "day.open_interest",
            )

        if values.get("volume") is None:
            values["volume"] = _first("volume", "vol", "day.volume")

        if values.get("sweep") is None:
            values["sweep"] = _first("sweep", "is_sweep", "isSweep")

        if values.get("trade_count") is None:
            values["trade_count"] = _first("trade_count", "trades", "day.trades")

        if values.get("trade_size") is None:
            values["trade_size"] = _first("trade_size", "size", "day.trade_size")

        if values.get("notional") is None:
            values["notional"] = _first(
                "notional",
                "premium",
                "trade_value",
                "day.notional",
            )

        if values.get("rvol") is None:
            values["rvol"] = _first("rvol", "relative_volume", "day.rvol")

        if values.get("iv_percentile") is None:
            values["iv_percentile"] = _first(
                "iv_percentile",
                "iv_pctile",
                "ivRank",
                "iv_percentile_52w",
            )

        if values.get("unusual_score") is None:
            values["unusual_score"] = _first("unusual_score", "score")

        if values.get("underlying_price") is None:
            values["underlying_price"] = _first(
                "underlying_price",
                "underlying.price",
                "underlying.last",
            )

        return values

    class Config:
        extra = "ignore"


class OptionChainSnapshot(BaseModel):
    underlying_asset: Optional[UnderlyingAsset] = None
    underlying_symbol: Optional[str] = None
    underlying_price: Optional[float] = None
    timestamp: Optional[str] = None
    contracts: Optional[List[OptionContractSnapshot]] = Field(default_factory=list)

    @root_validator(pre=True)
    def normalize_fields(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(values, dict):
            return values

        if values.get("underlying_symbol") is None:
            asset = values.get("underlying_asset") or values.get("underlying")
            if isinstance(asset, dict):
                values["underlying_symbol"] = asset.get("symbol") or asset.get("ticker")
            else:
                values["underlying_symbol"] = values.get("underlying_symbol")

        if values.get("underlying_price") is None:
            asset = values.get("underlying_asset") or values.get("underlying")
            if isinstance(asset, dict):
                values["underlying_price"] = asset.get("price") or asset.get("last")
            else:
                values["underlying_price"] = values.get("underlying_price")

        if values.get("contracts") is None:
            values["contracts"] = values.get("options") or values.get("contracts") or []

        return values

    class Config:
        extra = "ignore"


class OptionChainSnapshotResponse(BaseModel):
    results: Optional[List[OptionChainSnapshot]] = Field(default_factory=list)

    @root_validator(pre=True)
    def normalize_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        raw_results = values.get("results")
        if raw_results is None:
            for key in ("data", "snapshot", "result"):
                if key in values:
                    raw_results = values.get(key)
                    break

        if isinstance(raw_results, dict) and "results" in raw_results:
            raw_results = raw_results.get("results")

        if isinstance(raw_results, dict) and raw_results.get("contracts") is not None:
            raw_results = [raw_results]

        if raw_results is None and values.get("contracts") is not None:
            raw_results = [
                {
                    "underlying_symbol": values.get("symbol")
                    or values.get("underlying_symbol"),
                    "underlying_asset": values.get("underlying_asset")
                    or values.get("underlying"),
                    "contracts": values.get("contracts") or [],
                }
            ]

        if raw_results is not None:
            values["results"] = raw_results

        return values

    class Config:
        extra = "ignore"


class UnusualOptionsCandidate(BaseModel):
    options_ticker: str
    underlying_ticker: str
    direction: str
    expiration_date: date
    strike: float
    contract_type: str
    last_price: Optional[float]
    volume: Optional[int]
    open_interest: Optional[int]
    notional: float
    volume_oi_ratio: float
    dte_days: int
    score: float

    is_sweep: bool = False
    flow_type: str = "STANDARD"
    debug_alert: bool = False

    class Config:
        extra = "ignore"
