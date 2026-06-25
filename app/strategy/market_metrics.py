from __future__ import annotations

from typing import Any

from app.market.base import MarketSnapshot
from app.strategy import indicators


def build_market_metrics(market_snapshot: MarketSnapshot) -> dict[str, Any]:
    history = market_snapshot.daily_bars
    price = market_snapshot.price
    ma_values = {f"ma{period}": indicators.ma(history, period) for period in (5, 10, 20)}
    metrics: dict[str, Any] = {
        "price": price,
        "open": market_snapshot.open,
        "high": market_snapshot.high,
        "low": market_snapshot.low,
        "close": market_snapshot.close,
        "volume": market_snapshot.volume,
        "amount": market_snapshot.amount,
        "volume_ratio": indicators.volume_ratio(history, 5),
        "recent_high_10d": indicators.recent_high(history, 10),
        "recent_low_10d": indicators.recent_low(history, 10),
        "market_source": market_snapshot.source,
        "is_realtime": market_snapshot.is_realtime,
        "trade_date": market_snapshot.trade_date,
        "provider_errors": market_snapshot.provider_errors,
        **ma_values,
    }
    for period, ma_value in ma_values.items():
        metrics[f"distance_pct_{period}"] = indicators.distance_pct(price, ma_value)
    return metrics
