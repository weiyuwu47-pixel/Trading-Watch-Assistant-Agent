from __future__ import annotations

import time
from datetime import date, datetime, time as datetime_time, timedelta
from typing import Any, Protocol

from app.market.base import MarketMode, MarketSnapshot


class SnapshotProvider(Protocol):
    name: str

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        ...


class MultiSourceMarketProvider:
    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = str(stock_config.get("symbol", "")).strip()
        name = str(stock_config.get("name", symbol))
        market = str(stock_config.get("market", "A")).upper()
        effective_mode = _effective_mode(mode)

        if market == "A" and effective_mode == "close":
            providers: list[SnapshotProvider] = [
                AkshareDailyFallbackProvider(),
                TencentDailyFallbackProvider(),
            ]
        elif market == "A":
            providers = [
                EastMoneyRealtimeProvider(),
                TencentRealtimeProvider(),
                AkshareDailyFallbackProvider(),
                TencentDailyFallbackProvider(),
            ]
        elif market == "HK" and effective_mode == "close":
            providers = [
                AkshareHkDailyFallbackProvider(),
                SinaHkDailyFallbackProvider(),
            ]
        elif market == "HK":
            providers = [
                AkshareHkRealtimeProvider(),
                TencentHkRealtimeProvider(),
                AkshareHkDailyFallbackProvider(),
                SinaHkDailyFallbackProvider(),
            ]
        elif market in {"US", "USA"} and effective_mode == "close":
            providers = [
                AkshareUsDailyFallbackProvider(),
                YahooUsDailyFallbackProvider(),
                NasdaqUsDailyFallbackProvider(),
                StooqUsDailyFallbackProvider(),
            ]
        elif market in {"US", "USA"}:
            providers = [
                AkshareUsRealtimeProvider(),
                YahooUsRealtimeProvider(),
                AkshareUsDailyFallbackProvider(),
                YahooUsDailyFallbackProvider(),
                NasdaqUsDailyFallbackProvider(),
                StooqUsDailyFallbackProvider(),
            ]
        else:
            return _error_snapshot(stock_config, [f"unsupported_market: 暂未实现 {market} 市场行情接口"])

        errors: list[str] = []
        for provider in providers:
            try:
                snapshot = provider.get_snapshot(stock_config, mode=effective_mode)
                if snapshot.ok:
                    snapshot.provider_errors = errors
                    return snapshot
                errors.append(f"{provider.name}: {snapshot.error or '无有效 price/daily_bars'}")
            except Exception as exc:
                errors.append(f"{provider.name}: {type(exc).__name__}: {exc}")

        return MarketSnapshot(
            symbol=symbol,
            name=name,
            market=market,
            price=None,
            open=None,
            high=None,
            low=None,
            close=None,
            volume=None,
            amount=None,
            trade_date=None,
            source="none",
            is_realtime=False,
            daily_bars=[],
            error="; ".join(errors) or "所有行情数据源均失败",
            provider_errors=errors,
        )


class EastMoneyRealtimeProvider:
    name = "eastmoney_realtime"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = str(stock_config.get("symbol", "")).strip()
        quote = _retry(lambda: _fetch_eastmoney_quote(symbol), self.name)
        bars = _retry(lambda: _fetch_akshare_daily_em(symbol), "akshare_daily_em")
        latest = bars[-1]
        return MarketSnapshot(
            symbol=symbol,
            name=str(stock_config.get("name", quote.get("name") or symbol)),
            market=str(stock_config.get("market", "A")),
            price=quote["price"],
            open=quote.get("open") or latest.get("open"),
            high=quote.get("high") or latest.get("high"),
            low=quote.get("low") or latest.get("low"),
            close=quote["price"],
            volume=quote.get("volume") or latest.get("volume"),
            amount=quote.get("amount") or latest.get("amount"),
            trade_date=quote.get("trade_date") or latest.get("date"),
            source="eastmoney_realtime+akshare_daily_em",
            is_realtime=True,
            daily_bars=bars,
        )


class TencentRealtimeProvider:
    name = "tencent_realtime"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = str(stock_config.get("symbol", "")).strip()
        quote = _retry(lambda: _fetch_tencent_quote(symbol), self.name)
        bars = _retry(lambda: _fetch_tencent_daily(symbol), "akshare_daily_tx")
        latest = bars[-1]
        return MarketSnapshot(
            symbol=symbol,
            name=str(stock_config.get("name", quote.get("name") or symbol)),
            market=str(stock_config.get("market", "A")),
            price=quote["price"],
            open=quote.get("open") or latest.get("open"),
            high=quote.get("high") or latest.get("high"),
            low=quote.get("low") or latest.get("low"),
            close=quote["price"],
            volume=quote.get("volume") or latest.get("volume"),
            amount=quote.get("amount") or latest.get("amount"),
            trade_date=quote.get("trade_date") or latest.get("date"),
            source="tencent_realtime+akshare_daily_tx",
            is_realtime=True,
            daily_bars=bars,
        )


class AkshareDailyFallbackProvider:
    name = "akshare_daily_em"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = str(stock_config.get("symbol", "")).strip()
        bars = _retry(lambda: _fetch_akshare_daily_em(symbol), self.name)
        return _snapshot_from_latest_bar(stock_config, bars, source="akshare_daily_em_close")


class TencentDailyFallbackProvider:
    name = "akshare_daily_tx"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = str(stock_config.get("symbol", "")).strip()
        bars = _retry(lambda: _fetch_tencent_daily(symbol), self.name)
        return _snapshot_from_latest_bar(stock_config, bars, source="akshare_daily_tx_close")


class AkshareHkRealtimeProvider:
    name = "akshare_hk_spot_em"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = _hk_symbol(str(stock_config.get("symbol", "")).strip())
        quote = _retry(lambda: _fetch_hk_spot_em(symbol), self.name)
        bars = _retry(lambda: _fetch_hk_daily_em(symbol), "akshare_hk_daily_em")
        latest = bars[-1]
        return MarketSnapshot(
            symbol=symbol,
            name=str(stock_config.get("name", quote.get("name") or symbol)),
            market="HK",
            price=quote["price"],
            open=quote.get("open") or latest.get("open"),
            high=quote.get("high") or latest.get("high"),
            low=quote.get("low") or latest.get("low"),
            close=quote["price"],
            volume=quote.get("volume") or latest.get("volume"),
            amount=quote.get("amount") or latest.get("amount"),
            trade_date=quote.get("trade_date") or latest.get("date"),
            source="akshare_hk_spot_em+akshare_hk_daily_em",
            is_realtime=True,
            daily_bars=bars,
        )


class TencentHkRealtimeProvider:
    name = "tencent_hk_realtime"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = _hk_symbol(str(stock_config.get("symbol", "")).strip())
        quote = _retry(lambda: _fetch_tencent_hk_quote(symbol), self.name)
        bars = _retry(lambda: _fetch_hk_daily_sina(symbol), "akshare_hk_daily_sina")
        latest = bars[-1]
        return MarketSnapshot(
            symbol=symbol,
            name=str(stock_config.get("name", quote.get("name") or symbol)),
            market="HK",
            price=quote["price"],
            open=quote.get("open") or latest.get("open"),
            high=quote.get("high") or latest.get("high"),
            low=quote.get("low") or latest.get("low"),
            close=quote["price"],
            volume=quote.get("volume") or latest.get("volume"),
            amount=quote.get("amount") or latest.get("amount"),
            trade_date=quote.get("trade_date") or latest.get("date"),
            source="tencent_hk_realtime+akshare_hk_daily_sina",
            is_realtime=True,
            daily_bars=bars,
        )


class AkshareHkDailyFallbackProvider:
    name = "akshare_hk_daily_em"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = _hk_symbol(str(stock_config.get("symbol", "")).strip())
        bars = _retry(lambda: _fetch_hk_daily_em(symbol), self.name)
        return _snapshot_from_latest_bar({**stock_config, "symbol": symbol, "market": "HK"}, bars, source="akshare_hk_daily_em_close")


class SinaHkDailyFallbackProvider:
    name = "akshare_hk_daily_sina"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = _hk_symbol(str(stock_config.get("symbol", "")).strip())
        bars = _retry(lambda: _fetch_hk_daily_sina(symbol), self.name)
        return _snapshot_from_latest_bar({**stock_config, "symbol": symbol, "market": "HK"}, bars, source="akshare_hk_daily_sina_close")


class AkshareUsRealtimeProvider:
    name = "akshare_us_spot_em"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = _us_symbol(str(stock_config.get("symbol", "")).strip())
        quote = _retry(lambda: _fetch_us_spot_em(symbol), self.name)
        bars = _retry(lambda: _fetch_us_daily_em(quote.get("ak_code") or symbol), "akshare_us_daily_em")
        latest = bars[-1]
        return MarketSnapshot(
            symbol=symbol,
            name=str(stock_config.get("name", quote.get("name") or symbol)),
            market="US",
            price=quote["price"],
            open=quote.get("open") or latest.get("open"),
            high=quote.get("high") or latest.get("high"),
            low=quote.get("low") or latest.get("low"),
            close=quote["price"],
            volume=quote.get("volume") or latest.get("volume"),
            amount=quote.get("amount") or latest.get("amount"),
            trade_date=quote.get("trade_date") or latest.get("date"),
            source="akshare_us_spot_em+akshare_us_daily_em",
            is_realtime=True,
            daily_bars=bars,
        )


class YahooUsRealtimeProvider:
    name = "yahoo_us_realtime"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = _us_symbol(str(stock_config.get("symbol", "")).strip())
        bars = _retry(lambda: _fetch_us_daily_yahoo(symbol), "yahoo_us_daily")
        quote = _retry(lambda: _fetch_us_yahoo_quote(symbol, bars), self.name)
        latest = bars[-1]
        return MarketSnapshot(
            symbol=symbol,
            name=str(stock_config.get("name", symbol)),
            market="US",
            price=quote["price"],
            open=quote.get("open") or latest.get("open"),
            high=quote.get("high") or latest.get("high"),
            low=quote.get("low") or latest.get("low"),
            close=quote["price"],
            volume=quote.get("volume") or latest.get("volume"),
            amount=latest.get("amount"),
            trade_date=quote.get("trade_date") or latest.get("date"),
            source="yahoo_us_realtime+yahoo_us_daily",
            is_realtime=True,
            daily_bars=bars,
        )


class AkshareUsDailyFallbackProvider:
    name = "akshare_us_daily_em"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = _us_symbol(str(stock_config.get("symbol", "")).strip())
        bars = _retry(lambda: _fetch_us_daily_em(symbol), self.name)
        return _snapshot_from_latest_bar({**stock_config, "symbol": symbol, "market": "US"}, bars, source="akshare_us_daily_em_close")


class YahooUsDailyFallbackProvider:
    name = "yahoo_us_daily"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = _us_symbol(str(stock_config.get("symbol", "")).strip())
        bars = _retry(lambda: _fetch_us_daily_yahoo(symbol), self.name)
        return _snapshot_from_latest_bar({**stock_config, "symbol": symbol, "market": "US"}, bars, source="yahoo_us_daily_close")


class StooqUsDailyFallbackProvider:
    name = "stooq_us_daily"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = _us_symbol(str(stock_config.get("symbol", "")).strip())
        bars = _retry(lambda: _fetch_us_daily_stooq(symbol), self.name)
        return _snapshot_from_latest_bar({**stock_config, "symbol": symbol, "market": "US"}, bars, source="stooq_us_daily_close")


class NasdaqUsDailyFallbackProvider:
    name = "nasdaq_us_daily"

    def get_snapshot(self, stock_config: dict[str, Any], mode: MarketMode = "auto") -> MarketSnapshot:
        symbol = _us_symbol(str(stock_config.get("symbol", "")).strip())
        bars = _retry(lambda: _fetch_us_daily_nasdaq(symbol), self.name)
        return _snapshot_from_latest_bar({**stock_config, "symbol": symbol, "market": "US"}, bars, source="nasdaq_us_daily_close")


def _effective_mode(mode: MarketMode) -> MarketMode:
    if mode != "auto":
        return mode
    now = datetime.now().astimezone().time()
    if now >= datetime_time(15, 5) or now < datetime_time(9, 20):
        return "close"
    return "realtime"


def _retry(fn: Any, provider_name: str, attempts: int = 2, delay_seconds: float = 0.5) -> Any:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            if attempt < attempts:
                time.sleep(delay_seconds)
    raise RuntimeError(f"{provider_name} failed after {attempts} attempts: {' | '.join(errors)}")


def _fetch_akshare_daily_em(symbol: str) -> list[dict[str, Any]]:
    import akshare as ak
    import pandas as pd

    end = date.today()
    start = end - timedelta(days=240)
    raw = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="qfq",
        timeout=10,
    )
    if raw is None or raw.empty:
        raise RuntimeError("AkShare EastMoney 日 K 返回空")
    df = raw.rename(
        columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "change_pct",
        }
    ).copy()
    return _bars_from_dataframe(df, pd)


def _fetch_tencent_daily(symbol: str) -> list[dict[str, Any]]:
    import akshare as ak
    import pandas as pd

    end = date.today()
    start = end - timedelta(days=240)
    raw = ak.stock_zh_a_hist_tx(
        symbol=_prefixed_symbol(symbol),
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="qfq",
        timeout=10,
    )
    if raw is None or raw.empty:
        raise RuntimeError("AkShare Tencent 日 K 返回空")
    df = raw.rename(columns={"amount": "volume"}).copy()
    return _bars_from_dataframe(df, pd)


def _fetch_hk_daily_em(symbol: str) -> list[dict[str, Any]]:
    import akshare as ak
    import pandas as pd

    end = date.today()
    start = end - timedelta(days=260)
    raw = ak.stock_hk_hist(
        symbol=_hk_symbol(symbol),
        period="daily",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="",
    )
    if raw is None or raw.empty:
        raise RuntimeError("AkShare 港股 EastMoney 日 K 返回空")
    df = raw.rename(
        columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "change_pct",
        }
    ).copy()
    return _bars_from_dataframe(df, pd)


def _fetch_hk_daily_sina(symbol: str) -> list[dict[str, Any]]:
    import akshare as ak
    import pandas as pd

    raw = ak.stock_hk_daily(symbol=_hk_symbol(symbol), adjust="")
    if raw is None or raw.empty:
        raise RuntimeError("AkShare 港股 Sina 日 K 返回空")
    end = pd.Timestamp(date.today())
    start = end - pd.Timedelta(days=260)
    df = raw.copy()
    if "date" not in df.columns:
        raise RuntimeError("AkShare 港股 Sina 日 K 缺少 date 字段")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"].between(start, end)]
    return _bars_from_dataframe(df, pd)


def _fetch_us_daily_em(symbol: str) -> list[dict[str, Any]]:
    import akshare as ak
    import pandas as pd

    end = date.today()
    start = end - timedelta(days=320)
    ak_code = symbol if "." in symbol else _us_akshare_code(symbol)
    raw = ak.stock_us_hist(
        symbol=ak_code,
        period="daily",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="",
    )
    if raw is None or raw.empty:
        raise RuntimeError("AkShare 美股 EastMoney 日 K 返回空")
    df = raw.rename(
        columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "change_pct",
        }
    ).copy()
    return _bars_from_dataframe(df, pd)


def _fetch_us_daily_yahoo(symbol: str) -> list[dict[str, Any]]:
    import requests

    yahoo_symbol = _us_symbol(symbol)
    end_ts = int(datetime.now().timestamp())
    start_ts = int((datetime.now() - timedelta(days=420)).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
    params = {
        "period1": start_ts,
        "period2": end_ts,
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    resp = requests.get(url, params=params, headers=_market_headers(), timeout=10)
    resp.raise_for_status()
    result = ((resp.json().get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"Yahoo 美股日 K 返回空: {yahoo_symbol}")
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    bars: list[dict[str, Any]] = []
    for index, ts in enumerate(timestamps):
        close = _safe_index_float(quote.get("close"), index)
        open_price = _safe_index_float(quote.get("open"), index)
        high = _safe_index_float(quote.get("high"), index)
        low = _safe_index_float(quote.get("low"), index)
        volume = _safe_index_float(quote.get("volume"), index)
        if None in {close, open_price, high, low, volume}:
            continue
        bars.append(
            {
                "date": datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d"),
                "open": open_price,
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
                "amount": None,
                "change_pct": None,
            }
        )
    if not bars:
        raise RuntimeError(f"Yahoo 美股日 K 清洗后为空: {yahoo_symbol}")
    return bars


def _fetch_us_daily_stooq(symbol: str) -> list[dict[str, Any]]:
    import csv
    import io
    import requests

    stooq_symbol = f"{_us_symbol(symbol).lower()}.us"
    end = date.today()
    start = end - timedelta(days=420)
    url = "https://stooq.com/q/d/l/"
    params = {
        "s": stooq_symbol,
        "d1": start.strftime("%Y%m%d"),
        "d2": end.strftime("%Y%m%d"),
        "i": "d",
    }
    resp = requests.get(url, params=params, headers=_market_headers(), timeout=10)
    resp.raise_for_status()
    text = resp.text.strip()
    if not text or text.lower().startswith("no data"):
        raise RuntimeError(f"Stooq 美股日 K 返回空: {stooq_symbol}")
    rows = list(csv.DictReader(io.StringIO(text)))
    bars: list[dict[str, Any]] = []
    for row in rows:
        close = _safe_float(row.get("Close"))
        open_price = _safe_float(row.get("Open"))
        high = _safe_float(row.get("High"))
        low = _safe_float(row.get("Low"))
        volume = _safe_float(row.get("Volume"))
        if None in {close, open_price, high, low, volume}:
            continue
        bars.append(
            {
                "date": str(row.get("Date") or ""),
                "open": open_price,
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
                "amount": None,
                "change_pct": None,
            }
        )
    if not bars:
        raise RuntimeError(f"Stooq 美股日 K 清洗后为空: {stooq_symbol}")
    return bars


def _fetch_us_daily_nasdaq(symbol: str) -> list[dict[str, Any]]:
    import requests

    us_symbol = _us_symbol(symbol)
    end = date.today()
    start = end - timedelta(days=420)
    url = f"https://api.nasdaq.com/api/quote/{us_symbol}/historical"
    params = {
        "assetclass": "stocks",
        "fromdate": start.isoformat(),
        "todate": end.isoformat(),
        "limit": "9999",
    }
    headers = _market_headers() | {
        "Origin": "https://www.nasdaq.com",
        "Referer": f"https://www.nasdaq.com/market-activity/stocks/{us_symbol.lower()}/historical",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    rows = ((((resp.json().get("data") or {}).get("tradesTable") or {}).get("rows")) or [])
    if not rows:
        raise RuntimeError(f"Nasdaq 美股日 K 返回空: {us_symbol}")
    bars: list[dict[str, Any]] = []
    for row in reversed(rows):
        close = _money_float(row.get("close"))
        open_price = _money_float(row.get("open"))
        high = _money_float(row.get("high"))
        low = _money_float(row.get("low"))
        volume = _money_float(row.get("volume"))
        if None in {close, open_price, high, low, volume}:
            continue
        bars.append(
            {
                "date": datetime.strptime(str(row.get("date")), "%m/%d/%Y").strftime("%Y-%m-%d"),
                "open": open_price,
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
                "amount": None,
                "change_pct": None,
            }
        )
    if not bars:
        raise RuntimeError(f"Nasdaq 美股日 K 清洗后为空: {us_symbol}")
    return bars


def _fetch_eastmoney_quote(symbol: str) -> dict[str, Any]:
    import requests

    secid = _eastmoney_secid(symbol)
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f86",
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data") or {}
    if not data or data.get("f43") in (None, "-"):
        raise RuntimeError(f"EastMoney 实时报价为空: {payload}")
    trade_time = str(data.get("f86") or "")
    return {
        "name": data.get("f58"),
        "price": _scaled_price(data.get("f43")),
        "open": _scaled_price(data.get("f46")),
        "high": _scaled_price(data.get("f44")),
        "low": _scaled_price(data.get("f45")),
        "volume": _safe_float(data.get("f47")),
        "amount": _safe_float(data.get("f48")),
        "trade_date": _format_eastmoney_time(trade_time),
    }


def _fetch_hk_spot_em(symbol: str) -> dict[str, Any]:
    import akshare as ak

    hk_symbol = _hk_symbol(symbol)
    raw = ak.stock_hk_spot_em()
    if raw is None or raw.empty:
        raise RuntimeError("AkShare 港股 EastMoney 实时行情返回空")
    code = raw["代码"].astype(str).str.zfill(5)
    matched = raw[code == hk_symbol]
    if matched.empty:
        raise RuntimeError(f"AkShare 港股 EastMoney 实时行情未找到 {hk_symbol}")
    row = matched.iloc[0]
    price = _safe_float(row.get("最新价"))
    if price is None:
        raise RuntimeError(f"AkShare 港股 EastMoney 实时价格为空: {hk_symbol}")
    return {
        "name": row.get("名称"),
        "price": price,
        "open": _safe_float(row.get("今开")),
        "high": _safe_float(row.get("最高")),
        "low": _safe_float(row.get("最低")),
        "volume": _safe_float(row.get("成交量")),
        "amount": _safe_float(row.get("成交额")),
        "trade_date": date.today().isoformat(),
    }


def _fetch_us_spot_em(symbol: str) -> dict[str, Any]:
    import akshare as ak

    us_symbol = _us_symbol(symbol)
    raw = ak.stock_us_spot_em()
    if raw is None or raw.empty:
        raise RuntimeError("AkShare 美股 EastMoney 实时行情返回空")
    code = raw["代码"].astype(str).str.upper()
    matched = raw[code.str.endswith(f".{us_symbol}")]
    if matched.empty and "." in symbol:
        matched = raw[code == symbol.upper()]
    if matched.empty:
        raise RuntimeError(f"AkShare 美股 EastMoney 实时行情未找到 {us_symbol}")
    row = matched.iloc[0]
    price = _safe_float(row.get("最新价"))
    if price is None:
        raise RuntimeError(f"AkShare 美股 EastMoney 实时价格为空: {us_symbol}")
    return {
        "name": row.get("名称"),
        "ak_code": row.get("代码"),
        "price": price,
        "open": _safe_float(row.get("开盘价")),
        "high": _safe_float(row.get("最高价")),
        "low": _safe_float(row.get("最低价")),
        "volume": _safe_float(row.get("成交量")),
        "amount": _safe_float(row.get("成交额")),
        "trade_date": date.today().isoformat(),
    }


def _fetch_tencent_quote(symbol: str) -> dict[str, Any]:
    import requests

    resp = requests.get(f"https://qt.gtimg.cn/q={_prefixed_symbol(symbol)}", timeout=10)
    resp.raise_for_status()
    text = resp.text.strip()
    if '="' not in text:
        raise RuntimeError(f"Tencent 实时报价格式异常: {text[:100]}")
    body = text.split('="', 1)[1].rstrip('";')
    parts = body.split("~")
    if len(parts) < 35 or not parts[3]:
        raise RuntimeError(f"Tencent 实时报价字段不足: {text[:100]}")
    return {
        "name": parts[1],
        "price": float(parts[3]),
        "open": _safe_float(parts[5]),
        "high": _safe_float(parts[33]),
        "low": _safe_float(parts[34]),
        "volume": _safe_float(parts[6]),
        "amount": _safe_float(parts[37]) if len(parts) > 37 else None,
        "trade_date": _format_tencent_time(parts[30] if len(parts) > 30 else ""),
    }


def _fetch_tencent_hk_quote(symbol: str) -> dict[str, Any]:
    import requests

    hk_symbol = _hk_symbol(symbol)
    resp = requests.get(f"https://qt.gtimg.cn/q=hk{hk_symbol}", timeout=10)
    resp.raise_for_status()
    text = resp.text.strip()
    if '="' not in text:
        raise RuntimeError(f"Tencent 港股实时报价格式异常: {text[:100]}")
    body = text.split('="', 1)[1].rstrip('";')
    parts = body.split("~")
    if len(parts) < 10 or not parts[3]:
        raise RuntimeError(f"Tencent 港股实时报价字段不足: {text[:100]}")
    price = _safe_float(parts[3])
    if price is None:
        raise RuntimeError(f"Tencent 港股实时价格为空: {text[:100]}")
    return {
        "name": parts[1] if len(parts) > 1 else hk_symbol,
        "price": price,
        "open": _safe_float(parts[5] if len(parts) > 5 else None),
        "high": _safe_float(parts[33] if len(parts) > 33 else None),
        "low": _safe_float(parts[34] if len(parts) > 34 else None),
        "volume": _safe_float(parts[6] if len(parts) > 6 else None),
        "amount": _safe_float(parts[37] if len(parts) > 37 else None),
        "trade_date": _format_tencent_time(parts[30] if len(parts) > 30 else ""),
    }


def _fetch_us_yahoo_quote(symbol: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
    import requests

    yahoo_symbol = _us_symbol(symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
    resp = requests.get(url, params={"range": "5d", "interval": "1d"}, headers=_market_headers(), timeout=10)
    resp.raise_for_status()
    result = ((resp.json().get("chart") or {}).get("result") or [None])[0]
    latest = bars[-1]
    if not result:
        return {
            "price": latest.get("close"),
            "open": latest.get("open"),
            "high": latest.get("high"),
            "low": latest.get("low"),
            "volume": latest.get("volume"),
            "trade_date": latest.get("date"),
        }
    meta = result.get("meta") or {}
    price = _safe_float(meta.get("regularMarketPrice")) or _safe_float(latest.get("close"))
    return {
        "price": price,
        "open": _safe_float(meta.get("regularMarketOpen")) or latest.get("open"),
        "high": _safe_float(meta.get("regularMarketDayHigh")) or latest.get("high"),
        "low": _safe_float(meta.get("regularMarketDayLow")) or latest.get("low"),
        "volume": _safe_float(meta.get("regularMarketVolume")) or latest.get("volume"),
        "trade_date": latest.get("date"),
    }


def _snapshot_from_latest_bar(stock_config: dict[str, Any], bars: list[dict[str, Any]], source: str) -> MarketSnapshot:
    latest = bars[-1]
    close = _safe_float(latest.get("close"))
    return MarketSnapshot(
        symbol=str(stock_config.get("symbol", "")),
        name=str(stock_config.get("name", stock_config.get("symbol", ""))),
        market=str(stock_config.get("market", "A")),
        price=close,
        open=_safe_float(latest.get("open")),
        high=_safe_float(latest.get("high")),
        low=_safe_float(latest.get("low")),
        close=close,
        volume=_safe_float(latest.get("volume")),
        amount=_safe_float(latest.get("amount")),
        trade_date=str(latest.get("date") or ""),
        source=source,
        is_realtime=False,
        daily_bars=bars,
    )


def _bars_from_dataframe(df: Any, pd: Any) -> list[dict[str, Any]]:
    required = {"date", "open", "close", "high", "low", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"日 K 字段缺失: {', '.join(sorted(missing))}")
    cleaned = df.copy()
    for col in ["open", "close", "high", "low", "volume", "amount", "change_pct"]:
        if col in cleaned.columns:
            cleaned[col] = pd.to_numeric(cleaned[col], errors="coerce")
    cleaned["date"] = pd.to_datetime(cleaned["date"], errors="coerce")
    cleaned = cleaned.dropna(subset=["date", "open", "close", "high", "low", "volume"]).sort_values("date")
    if cleaned.empty:
        raise RuntimeError("日 K 清洗后为空")
    bars: list[dict[str, Any]] = []
    for _, row in cleaned.iterrows():
        bars.append(
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "open": float(row["open"]),
                "close": float(row["close"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "volume": float(row["volume"]),
                "amount": _safe_float(row.get("amount")),
                "change_pct": _safe_float(row.get("change_pct")),
            }
        )
    return bars


def _error_snapshot(stock_config: dict[str, Any], errors: list[str]) -> MarketSnapshot:
    symbol = str(stock_config.get("symbol", ""))
    return MarketSnapshot(
        symbol=symbol,
        name=str(stock_config.get("name", symbol)),
        market=str(stock_config.get("market", "A")),
        price=None,
        open=None,
        high=None,
        low=None,
        close=None,
        volume=None,
        amount=None,
        trade_date=None,
        source="none",
        is_realtime=False,
        daily_bars=[],
        error="; ".join(errors),
        provider_errors=errors,
    )


def _prefixed_symbol(symbol: str) -> str:
    return f"sh{symbol}" if symbol.startswith(("5", "6", "9")) else f"sz{symbol}"


def _eastmoney_secid(symbol: str) -> str:
    market_id = "1" if symbol.startswith(("5", "6", "9")) else "0"
    return f"{market_id}.{symbol}"


def _hk_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper().replace("HK", "").replace(".", "")
    if not cleaned:
        return cleaned
    return cleaned.zfill(5)


def _us_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper()
    if "." in cleaned and cleaned.split(".", 1)[0].isdigit():
        return cleaned.split(".", 1)[1]
    return cleaned.replace("US.", "").replace("USA.", "")


def _us_akshare_code(symbol: str) -> str:
    quote = _fetch_us_spot_em(symbol)
    ak_code = str(quote.get("ak_code") or "")
    if not ak_code:
        raise RuntimeError(f"无法映射美股 AkShare 代码: {symbol}")
    return ak_code


def _scaled_price(value: Any) -> float | None:
    number = _safe_float(value)
    if number is None:
        return None
    return number / 100


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _money_float(value: Any) -> float | None:
    if value is None:
        return None
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    return _safe_float(cleaned)


def _safe_index_float(values: Any, index: int) -> float | None:
    if not values or index >= len(values):
        return None
    return _safe_float(values[index])


def _market_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
        "Accept": "application/json,text/csv,text/plain,*/*",
    }


def _format_tencent_time(value: str) -> str | None:
    if "/" in value:
        date_part = value.split(" ", 1)[0]
        parts = date_part.split("/")
        if len(parts) == 3 and all(parts):
            return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
    if len(value) < 8:
        return None
    return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"


def _format_eastmoney_time(value: str) -> str | None:
    if len(value) < 8:
        return None
    return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
