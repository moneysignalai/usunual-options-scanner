from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic.v1 import BaseModel, Field


class UnderlyingSnapshot(BaseModel):
    symbol: Optional[str] = None
    last_price: Optional[float] = None

    class Config:
        extra = "ignore"


class OptionContractSnapshot(BaseModel):
    options_ticker: Optional[str] = Field(None, alias="options_ticker")
    underlying_ticker: Optional[str] = Field(None, alias="underlying_ticker")
    expiration_date: Optional[date] = None
    strike: Optional[float] = None
    contract_type: Optional[str] = None
    last_price: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = Field(None, alias="open_interest")
    sweep: Optional[bool] = None

    class Config:
        allow_population_by_field_name = True
        extra = "ignore"


class OptionChainSnapshot(BaseModel):
    underlying: Optional[UnderlyingSnapshot] = None
    options: List[OptionContractSnapshot] = Field(default_factory=list)

    class Config:
        extra = "ignore"


class OptionChainSnapshotResponse(BaseModel):
    data: OptionChainSnapshot

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

    class Config:
        extra = "ignore"
