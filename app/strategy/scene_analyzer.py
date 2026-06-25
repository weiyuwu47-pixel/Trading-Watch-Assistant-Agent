from __future__ import annotations

import json
from typing import Any

from app.config import load_app_config
from app.llm.deepseek_provider import DeepSeekProvider
from app.market.base import MarketSnapshot


class SceneAnalyzer:
    def __init__(self, provider: DeepSeekProvider | None = None) -> None:
        if provider is not None:
            self.provider = provider
        else:
            config = load_app_config()
            self.provider = DeepSeekProvider(config.deepseek_api_key, config.deepseek_base_url, config.deepseek_model, timeout=30)

    def analyze(self, stock_config: dict[str, Any], market_snapshot: MarketSnapshot, metrics: dict[str, Any]) -> dict[str, Any]:
        human_strategy = str(stock_config.get("human_strategy_text") or "").strip()
        if not human_strategy:
            return _review("该股票未配置 human_strategy_text，无法使用 hybrid mode")
        if not market_snapshot.ok:
            return _review(f"行情数据异常：{market_snapshot.error}")

        system_prompt = "你是个人盯盘策略场景识别助手，只能根据用户原始策略和当前行情判断是否触发既有场景。"
        user_prompt = _build_prompt(stock_config, market_snapshot, metrics, human_strategy)
        decision = self.provider.complete_json(system_prompt, user_prompt, max_tokens=800)
        return _normalize_decision(decision)


def _build_prompt(stock_config: dict[str, Any], market_snapshot: MarketSnapshot, metrics: dict[str, Any], human_strategy: str) -> str:
    stock_brief = {
        "symbol": stock_config.get("symbol"),
        "name": stock_config.get("name"),
        "market": stock_config.get("market"),
        "current_position_shares": stock_config.get("current_position_shares"),
        "cost_price": stock_config.get("cost_price"),
        "max_position_shares": stock_config.get("max_position_shares"),
        "base_position_shares": stock_config.get("base_position_shares"),
        "t_position_shares": stock_config.get("t_position_shares"),
        "t_cash_budget": stock_config.get("t_cash_budget"),
        "min_lot": stock_config.get("min_lot", 100),
        "principles": stock_config.get("principles") or [],
    }
    market_brief = {
        "price": market_snapshot.price,
        "open": market_snapshot.open,
        "high": market_snapshot.high,
        "low": market_snapshot.low,
        "close": market_snapshot.close,
        "volume": market_snapshot.volume,
        "amount": market_snapshot.amount,
        "trade_date": market_snapshot.trade_date,
        "source": market_snapshot.source,
        "is_realtime": market_snapshot.is_realtime,
    }
    latest_bars = market_snapshot.daily_bars[-5:] if market_snapshot.daily_bars else []
    useful_metrics = {
        key: metrics.get(key)
        for key in [
            "ma5",
            "ma10",
            "ma20",
            "volume_ratio",
            "recent_high_10d",
            "recent_low_10d",
            "distance_pct_ma5",
            "distance_pct_ma10",
            "distance_pct_ma20",
        ]
    }
    return f"""
请严格根据 human_strategy_text 判断当前行情属于哪个策略场景，并输出 JSON。

硬性规则：
1. 只能依据 human_strategy_text 判断，不得创造新策略。
2. 不得因为成本价接近而自行卖出。
3. 不得因为怕踏空而自行买入。
4. 不得因为亏损而无信号补仓。
5. 如果当前价格未进入某卖出区间，不能触发该卖出规则。
6. 如果 action 是 buy/sell，必须引用 matched_strategy_clause，且该片段必须来自 human_strategy_text。
7. 如果没有明确匹配的策略条款，action 必须是 hold 或 review。
8. 如果不确定，输出 review，confidence=low，needs_human_review=true。
9. 成本价只用于仓位和风险管理，不是买卖理由。
10. 输出必须是 JSON，不要 markdown，不要额外解释。

JSON 格式：
{{
  "action": "buy | sell | hold | review",
  "shares": 0,
  "scene": "当前盘面场景",
  "matched_strategy_clause": "匹配到的自然语言策略原文片段",
  "excluded_clauses": ["未触发的策略条件"],
  "reason": "一句话理由",
  "confidence": "high | medium | low",
  "needs_human_review": false
}}

股票配置：
{json.dumps(stock_brief, ensure_ascii=False)}

当前行情：
{json.dumps(market_brief, ensure_ascii=False)}

关键指标：
{json.dumps(useful_metrics, ensure_ascii=False)}

最近日K：
{json.dumps(latest_bars, ensure_ascii=False)}

human_strategy_text：
{human_strategy}
""".strip()


def _normalize_decision(decision: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "action": str(decision.get("action") or "review").lower(),
        "shares": decision.get("shares", 0),
        "scene": str(decision.get("scene") or ""),
        "matched_strategy_clause": str(decision.get("matched_strategy_clause") or ""),
        "excluded_clauses": decision.get("excluded_clauses") if isinstance(decision.get("excluded_clauses"), list) else [],
        "reason": str(decision.get("reason") or ""),
        "confidence": str(decision.get("confidence") or "low").lower(),
        "needs_human_review": bool(decision.get("needs_human_review", False)),
    }
    if normalized["action"] not in {"buy", "sell", "hold", "review"}:
        normalized["action"] = "review"
    if normalized["confidence"] not in {"high", "medium", "low"}:
        normalized["confidence"] = "low"
    return normalized


def _review(reason: str) -> dict[str, Any]:
    return {
        "action": "review",
        "shares": 0,
        "scene": "无法判断当前盘面场景",
        "matched_strategy_clause": "",
        "excluded_clauses": [],
        "reason": reason,
        "confidence": "low",
        "needs_human_review": True,
    }
