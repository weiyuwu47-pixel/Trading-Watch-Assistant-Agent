from __future__ import annotations

from typing import Any


def normalize_symbol(symbol: Any, market: str | None = None) -> str:
    raw = str(symbol or "").strip().upper()
    if not raw:
        return ""
    if (market or "").upper() == "HK" or raw.startswith("HK"):
        return raw.replace("HK", "").replace(".", "").zfill(5)
    if (market or "").upper() in {"US", "USA"}:
        if "." in raw and raw.split(".", 1)[0].isdigit():
            return raw.split(".", 1)[1]
        return raw.replace("US.", "").replace("USA.", "")
    return raw


def stock_symbol_matches(stock: dict[str, Any], symbol: str) -> bool:
    market = str(stock.get("market", "")).upper()
    configured = str(stock.get("symbol", "")).strip()
    return normalize_symbol(configured, market) == normalize_symbol(symbol, market if market else None)


def find_stock(stocks: list[dict[str, Any]], symbol: str) -> dict[str, Any] | None:
    return next((stock for stock in stocks if stock_symbol_matches(stock, symbol)), None)
