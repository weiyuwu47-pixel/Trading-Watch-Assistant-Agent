from __future__ import annotations

import re
from typing import Any

from app.market.base import MarketSnapshot
from app.strategy.position_sizer import floor_to_lot, legal_buy_shares, legal_sell_shares


class DecisionGuard:
    def guard(
        self,
        llm_decision: dict[str, Any],
        stock_config: dict[str, Any],
        market_snapshot: MarketSnapshot,
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        warnings: list[str] = []
        action = str(llm_decision.get("action") or "review").lower()
        if action not in {"buy", "sell", "hold", "review"}:
            return _final("review", 0, "LLM 输出 action 非法，转为人工复核", llm_decision, warnings + ["invalid_action"])

        confidence = str(llm_decision.get("confidence") or "low").lower()
        needs_review = bool(llm_decision.get("needs_human_review", False))
        if confidence == "low":
            return _final("review", 0, "LLM 置信度低，转为人工复核", llm_decision, warnings + ["low_confidence"])
        if needs_review:
            return _final("review", 0, "LLM 标记需要人工复核", llm_decision, warnings + ["needs_human_review"])

        shares = _parse_shares(llm_decision.get("shares"))
        min_lot = int(stock_config.get("min_lot", 100) or 100)
        if action in {"hold", "review"}:
            return _final(action, 0, _reason(llm_decision, action), llm_decision, warnings)
        if shares is None or shares <= 0:
            return _final("review", 0, "LLM 输出买卖股数缺失或非法，转为人工复核", llm_decision, warnings + ["invalid_shares"])

        matched_clause = str(llm_decision.get("matched_strategy_clause") or "").strip()
        if not matched_clause:
            return _final("review", 0, "买卖动作缺少匹配到的原始策略条款，转为人工复核", llm_decision, warnings + ["missing_matched_strategy_clause"])

        max_text_shares = _max_strategy_shares(str(stock_config.get("human_strategy_text") or ""), action)
        if max_text_shares is None:
            return _final("review", 0, "无法从策略原文确认本次买卖最大股数，转为人工复核", llm_decision, warnings + ["unknown_strategy_share_limit"])
        if shares > max_text_shares:
            shares = max_text_shares
            warnings.append("shares_reduced_to_strategy_text_limit")

        floored = floor_to_lot(shares, min_lot)
        if floored != shares:
            warnings.append("shares_rounded_down_to_min_lot")
        shares = floored
        if shares <= 0:
            fallback = "hold" if action in {"buy", "sell"} else "review"
            return _final(fallback, 0, "股数按最小交易单位取整后为 0，默认不操作", llm_decision, warnings + ["zero_after_lot_rounding"])

        reason = _reason(llm_decision, action)
        if _violates_principles(reason):
            return _final("review", 0, "LLM 理由可能违反交易原则，转为人工复核", llm_decision, warnings + ["principle_violation"])

        price = float(market_snapshot.price or 0)
        if action == "buy":
            legal = legal_buy_shares(
                requested_shares=shares,
                price=price,
                current_position_shares=int(stock_config.get("current_position_shares", 0) or 0),
                max_invest_amount=float(stock_config.get("max_invest_amount", 0) or 0),
                max_position_shares=int(stock_config.get("max_position_shares", 0) or 0),
                min_lot=min_lot,
            )
            if legal < shares:
                warnings.append("buy_shares_reduced_by_position_guard")
            if legal <= 0:
                return _final("hold", 0, "触发买入场景，但买入会超过资金或最大持仓上限，默认不买", llm_decision, warnings)
            return _final("buy", legal, reason, llm_decision, warnings)

        current_position = int(stock_config.get("current_position_shares", 0) or 0)
        base_position = stock_config.get("base_position_shares")
        legal = legal_sell_shares(
            requested_shares=shares,
            current_position_shares=current_position,
            min_lot=min_lot,
            keep_min_shares=int(base_position) if base_position is not None else None,
        )
        if legal < shares:
            warnings.append("sell_shares_reduced_by_position_guard")
        if legal <= 0:
            if base_position is not None and current_position <= int(base_position):
                return _final("hold", 0, "触发卖出场景，但卖出会低于底仓保护，默认不动", llm_decision, warnings + ["base_position_protected"])
            return _final("hold", 0, "触发卖出场景，但当前无合法可卖股数，默认不动", llm_decision, warnings)
        return _final("sell", legal, reason, llm_decision, warnings)


def _final(action: str, shares: int, reason: str, llm_decision: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    return {
        "action": action,
        "shares": int(shares),
        "reason": reason,
        "scene": str(llm_decision.get("scene") or ""),
        "matched_strategy_clause": str(llm_decision.get("matched_strategy_clause") or ""),
        "excluded_clauses": llm_decision.get("excluded_clauses") if isinstance(llm_decision.get("excluded_clauses"), list) else [],
        "confidence": str(llm_decision.get("confidence") or "low").lower(),
        "needs_human_review": bool(llm_decision.get("needs_human_review", False)) or action == "review",
        "guard_warnings": warnings,
    }


def _parse_shares(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def _max_strategy_shares(text: str, action: str) -> int | None:
    if action == "buy":
        patterns = [
            r"(?:买入|买|加仓|加)\s*(\d+)(?:\s*[-–—到至]\s*(\d+))?\s*股",
            r"可(?:再)?加仓\s*(\d+)(?:\s*[-–—到至]\s*(\d+))?\s*股",
        ]
    else:
        patterns = [
            r"(?:卖出|卖|减仓|减)\s*(\d+)(?:\s*[-–—到至]\s*(\d+))?\s*股",
            r"卖\s*(\d+)(?:\s*[-–—到至]\s*(\d+))?\s*股",
        ]
    values: list[int] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            values.append(int(match.group(2) or match.group(1)))
    return max(values) if values else None


def _reason(llm_decision: dict[str, Any], action: str) -> str:
    reason = str(llm_decision.get("reason") or "").strip()
    if reason:
        return reason
    if action == "hold":
        return "当前盘面未明确匹配买卖策略条款，默认不操作"
    if action == "review":
        return "当前盘面无法明确匹配策略条款，需人工复核"
    return "当前盘面匹配原始策略条款"


def _violates_principles(reason: str) -> bool:
    banned = ["回本", "怕踏空", "摊薄成本", "降低成本", "亏损补仓", "为了盈利目标"]
    return any(item in reason for item in banned)
