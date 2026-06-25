from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal


Action = Literal["buy", "sell", "hold", "review"]


@dataclass(slots=True)
class MarketData:
    symbol: str
    price: float | None = None
    change_pct: float | None = None
    volume: float | None = None
    history: Any | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.price is not None and self.history is not None


@dataclass(slots=True)
class Signal:
    symbol: str
    name: str
    action: Action
    shares: int
    price: float | None
    rule_id: str
    reason: str
    triggered_at: datetime
    raw_metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["triggered_at"] = self.triggered_at.isoformat(timespec="seconds")
        return data
