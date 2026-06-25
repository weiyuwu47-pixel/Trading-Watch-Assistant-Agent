from __future__ import annotations

import argparse
import json

from app.config import load_app_config, load_stock_configs
from app.market.multi_source_provider import MultiSourceMarketProvider
from app.stock_utils import find_stock
from app.strategy.decision_guard import DecisionGuard
from app.strategy.market_metrics import build_market_metrics
from app.strategy.scene_analyzer import SceneAnalyzer


def main() -> None:
    parser = argparse.ArgumentParser(description="测试 hybrid 智能盘面理解，不写库、不推送")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--mode", choices=["auto", "realtime", "close"], default="close")
    args = parser.parse_args()

    config = load_app_config()
    stock = find_stock(load_stock_configs(config.stock_config_path), args.symbol)
    if stock is None:
        raise SystemExit(f"未找到股票: {args.symbol}")

    snapshot = MultiSourceMarketProvider().get_snapshot(stock, mode=args.mode)
    metrics = build_market_metrics(snapshot)
    raw_decision = SceneAnalyzer().analyze(stock, snapshot, metrics)
    guarded = DecisionGuard().guard(raw_decision, stock, snapshot, metrics)

    output = {
        "symbol": stock.get("symbol"),
        "name": stock.get("name"),
        "price": snapshot.price,
        "market_source": snapshot.source,
        "trade_date": snapshot.trade_date,
        "is_realtime": snapshot.is_realtime,
        "scene": raw_decision.get("scene"),
        "matched_strategy_clause": raw_decision.get("matched_strategy_clause"),
        "excluded_clauses": raw_decision.get("excluded_clauses"),
        "raw_llm_action": raw_decision.get("action"),
        "raw_llm_shares": raw_decision.get("shares"),
        "raw_llm_confidence": raw_decision.get("confidence"),
        "guarded_action": guarded.get("action"),
        "guarded_shares": guarded.get("shares"),
        "guarded_reason": guarded.get("reason"),
        "guard_warnings": guarded.get("guard_warnings"),
        "needs_human_review": guarded.get("needs_human_review"),
        "provider_errors": snapshot.provider_errors,
        "market_error": snapshot.error,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
