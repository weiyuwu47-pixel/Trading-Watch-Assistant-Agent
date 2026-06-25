from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.models import MarketData


class AkShareProvider:
    def get_market_data(self, stock_config: dict[str, Any]) -> MarketData:
        symbol = str(stock_config.get("symbol", "")).strip()
        market = str(stock_config.get("market", "A")).upper()
        if market not in {"A", "HK", "US", "USA"}:
            return MarketData(symbol=symbol, error=f"暂未实现 {market} 市场行情接口")

        try:
            import akshare as ak
            import pandas as pd
        except Exception as exc:
            return MarketData(symbol=symbol, error=f"AkShare 或 pandas 未安装: {exc}")

        try:
            end = date.today()
            start = end - timedelta(days=180)
            if market == "HK":
                raw = ak.stock_hk_hist(
                    symbol=_hk_symbol(symbol),
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="",
                )
            elif market in {"US", "USA"}:
                raw = ak.stock_us_hist(
                    symbol=symbol if "." in symbol else _us_akshare_code(ak, symbol),
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="",
                )
            else:
                raw = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
                )
            if raw is None or raw.empty:
                return MarketData(symbol=symbol, error="AkShare 返回空行情")

            required = {"日期", "开盘", "收盘", "最高", "最低", "成交量"}
            missing = required - set(raw.columns)
            if missing:
                return MarketData(symbol=symbol, error=f"AkShare 行情字段缺失: {', '.join(sorted(missing))}")

            df = raw.rename(
                columns={
                    "日期": "date",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                    "涨跌幅": "change_pct",
                }
            ).copy()
            for col in ["open", "close", "high", "low", "volume", "change_pct"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date", "close", "high", "low", "volume"]).sort_values("date")
            if df.empty:
                return MarketData(symbol=symbol, error="行情清洗后为空")

            latest = df.iloc[-1]
            return MarketData(
                symbol=symbol,
                price=float(latest["close"]),
                change_pct=float(latest["change_pct"]) if "change_pct" in df.columns and pd.notna(latest.get("change_pct")) else None,
                volume=float(latest["volume"]),
                history=df.reset_index(drop=True),
            )
        except Exception as exc:
            return MarketData(symbol=symbol, error=f"AkShare 获取行情失败: {exc}")


def _hk_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("HK", "").replace(".", "").zfill(5)


def _us_akshare_code(ak: Any, symbol: str) -> str:
    us_symbol = symbol.strip().upper()
    raw = ak.stock_us_spot_em()
    if raw is None or raw.empty:
        raise RuntimeError("AkShare 美股实时行情返回空，无法映射代码")
    code = raw["代码"].astype(str).str.upper()
    matched = raw[code.str.endswith(f".{us_symbol}")]
    if matched.empty:
        raise RuntimeError(f"AkShare 美股实时行情未找到 {us_symbol}")
    return str(matched.iloc[0]["代码"])
