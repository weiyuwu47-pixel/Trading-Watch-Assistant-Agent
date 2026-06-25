from __future__ import annotations

from typing import Any


def normalize_history(history: Any) -> Any:
    if history is None:
        return None
    if hasattr(history, "empty"):
        return history
    if isinstance(history, list):
        try:
            import pandas as pd

            df = pd.DataFrame(history)
            if df.empty:
                return df
            for col in ["open", "close", "high", "low", "volume", "amount", "change_pct"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                df = df.sort_values("date")
            return df.reset_index(drop=True)
        except Exception:
            return None
    return history


def _valid_history(history: Any, min_rows: int = 1) -> bool:
    history = normalize_history(history)
    return history is not None and hasattr(history, "empty") and not history.empty and len(history) >= min_rows


def ma(history: Any, period: int) -> float | None:
    history = normalize_history(history)
    if not _valid_history(history, period):
        return None
    series = history["close"].rolling(window=period).mean()
    value = series.iloc[-1]
    return None if value != value else float(value)


def recent_high(history: Any, lookback_days: int) -> float | None:
    history = normalize_history(history)
    if not _valid_history(history, lookback_days + 1):
        return None
    window = history.iloc[-(lookback_days + 1) : -1]
    return float(window["high"].max())


def recent_low(history: Any, lookback_days: int) -> float | None:
    history = normalize_history(history)
    if not _valid_history(history, lookback_days + 1):
        return None
    window = history.iloc[-(lookback_days + 1) : -1]
    return float(window["low"].min())


def volume_ratio(history: Any, period: int = 5) -> float | None:
    history = normalize_history(history)
    if not _valid_history(history, period + 1):
        return None
    current_volume = float(history["volume"].iloc[-1])
    avg_volume = float(history["volume"].iloc[-(period + 1) : -1].mean())
    if avg_volume <= 0:
        return None
    return current_volume / avg_volume


def distance_pct(price: float | None, base_value: float | None) -> float | None:
    if price is None or base_value is None or base_value == 0:
        return None
    return (price - base_value) / base_value * 100
