from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


MarketMode = Literal["auto", "realtime", "close"]


@dataclass(slots=True)
class MarketSnapshot:
    symbol: str
    name: str
    market: str
    price: float | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    amount: float | None
    trade_date: str | None
    source: str
    is_realtime: bool
    daily_bars: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    provider_errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and self.price is not None and bool(self.daily_bars)
