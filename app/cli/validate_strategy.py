from __future__ import annotations

from app.config import load_app_config, load_stock_configs
from app.strategy.validator import validate_stocks


def main() -> None:
    config = load_app_config()
    stocks = load_stock_configs(config.stock_config_path)
    errors = validate_stocks(stocks)
    if errors:
        print("策略校验失败：")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(f"策略校验通过：共 {len(stocks)} 只股票")


if __name__ == "__main__":
    main()
