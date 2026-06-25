from __future__ import annotations

import argparse

from app.config import load_app_config, load_stock_configs
from app.strategy.explainer import explain_stock_strategy


def main() -> None:
    parser = argparse.ArgumentParser(description="将 YAML 策略反译成自然语言摘要")
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()

    config = load_app_config()
    stocks = load_stock_configs(config.stock_config_path)
    stock = next((item for item in stocks if str(item.get("symbol")) == args.symbol), None)
    if stock is None:
        raise SystemExit(f"未找到股票: {args.symbol}")

    print(explain_stock_strategy(stock))


if __name__ == "__main__":
    main()
