from __future__ import annotations

import argparse

from app.config import load_app_config
from app.scheduler import run_once


def main() -> None:
    parser = argparse.ArgumentParser(description="手动运行一次盯盘任务")
    parser.add_argument("--symbol", help="只运行指定股票代码，例如 002299")
    parser.add_argument("--mode", choices=["auto", "realtime", "close"], default="auto", help="行情模式：auto/realtime/close")
    parser.add_argument("--decision-mode", choices=["rule", "hybrid"], help="决策模式：rule/hybrid；不传则读取股票配置")
    args = parser.parse_args()

    config = load_app_config()
    try:
        result = run_once(config, symbol=args.symbol, mode=args.mode, decision_mode=args.decision_mode)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"运行状态: {result.status}，{result.message}")


if __name__ == "__main__":
    main()
