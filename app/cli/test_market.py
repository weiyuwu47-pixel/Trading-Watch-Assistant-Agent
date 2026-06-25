from __future__ import annotations

import argparse
import json

from app.config import load_app_config, load_stock_configs
from app.market.multi_source_provider import MultiSourceMarketProvider
from app.stock_utils import find_stock
from app.strategy import indicators


def main() -> None:
    parser = argparse.ArgumentParser(description="测试行情数据源，不触发策略、LLM 或通知")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--mode", choices=["auto", "realtime", "close"], default="auto")
    args = parser.parse_args()

    config = load_app_config()
    stocks = load_stock_configs(config.stock_config_path)
    stock = find_stock(stocks, args.symbol)
    if stock is None:
        raise SystemExit(f"未找到股票: {args.symbol}")

    snapshot = MultiSourceMarketProvider().get_snapshot(stock, mode=args.mode)
    history = snapshot.daily_bars
    output = {
        "symbol": snapshot.symbol,
        "name": snapshot.name,
        "price": snapshot.price,
        "open": snapshot.open,
        "high": snapshot.high,
        "low": snapshot.low,
        "close": snapshot.close,
        "volume": snapshot.volume,
        "amount": snapshot.amount,
        "trade_date": snapshot.trade_date,
        "source": snapshot.source,
        "is_realtime": snapshot.is_realtime,
        "ma5": indicators.ma(history, 5),
        "ma10": indicators.ma(history, 10),
        "ma20": indicators.ma(history, 20),
        "volume_ratio": indicators.volume_ratio(history, 5),
        "recent_high_10d": indicators.recent_high(history, 10),
        "recent_low_10d": indicators.recent_low(history, 10),
        "provider_errors": snapshot.provider_errors,
        "error": snapshot.error,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
