from __future__ import annotations

from typing import Any


def explain_stock_strategy(stock: dict[str, Any]) -> str:
    lines: list[str] = []
    symbol = stock.get("symbol", "")
    name = stock.get("name", symbol)
    lines.append(f"股票：{name} {symbol}")
    lines.append(f"有效期：{stock.get('valid_until', '未设置')}")
    lines.append("")
    lines.append("买入条件：")
    lines.extend(_explain_rules(stock.get("buy_rules") or [], default_action="buy"))
    lines.append("")
    lines.append("卖出条件：")
    lines.extend(_explain_rules(stock.get("sell_rules") or [], default_action="sell"))
    lines.append("")
    lines.append("不动条件：")
    lines.append(f"- {(stock.get('hold_rule') or {}).get('explanation_template', '未触发预设买卖条件，默认不操作')}")
    lines.append("")
    lines.append("禁止操作：")
    lines.extend(_explain_block_rules(stock.get("block_buy_rules") or []))
    lines.append("")
    lines.append("仓位保护：")
    lines.extend(_explain_position(stock))
    return "\n".join(lines)


def _explain_rules(rules: list[dict[str, Any]], default_action: str) -> list[str]:
    if not rules:
        return ["- 无"]
    return [f"- {_explain_rule(rule, default_action)}" for rule in rules]


def _explain_rule(rule: dict[str, Any], default_action: str) -> str:
    rule_id = rule.get("id", "未命名规则")
    action = rule.get("action", default_action)
    action_label = "买入" if action == "buy" else "卖出" if action == "sell" else str(action)
    shares = rule.get("shares")
    share_text = f"{action_label}{shares}股" if shares else action_label
    condition = _rule_condition_text(rule)
    position_condition = _position_condition_text(rule.get("position_condition"))
    extra = f"；{position_condition}" if position_condition else ""
    reason = rule.get("description") or rule.get("explanation_template") or ""
    reason_text = f"；说明：{reason}" if reason else ""
    return f"{rule_id}：当{condition}时，{share_text}{extra}{reason_text}"


def _rule_condition_text(rule: dict[str, Any]) -> str:
    rule_type = rule.get("type")
    if rule_type == "breakout_recent_high":
        return f"价格突破近{rule.get('lookback_days')}日高点，且量比 > {rule.get('volume_ratio_gt', '未限制')}"
    if rule_type == "pullback_ma":
        return f"价格回踩MA{rule.get('ma')}附近，偏离不超过{rule.get('tolerance_pct')}%，且量比 < {rule.get('volume_ratio_lt', '未限制')}"
    if rule_type == "break_ma":
        return f"价格跌破MA{rule.get('ma')}"
    if rule_type == "far_above_ma":
        return f"价格高于MA{rule.get('ma')}超过{rule.get('distance_pct_gt')}%"
    if rule_type == "reclaim_price_level":
        return f"价格站回 >= {rule.get('price_gte')}，且量比 > {rule.get('volume_ratio_gt', '未限制')}"
    if rule_type == "break_price_level":
        return f"价格突破 > {rule.get('price_gt')}，且量比 > {rule.get('volume_ratio_gt', '未限制')}"
    if rule_type == "break_price_level_down":
        return f"价格跌破 < {rule.get('price_lt')}"
    if rule_type == "stabilize_in_price_range":
        parts = [f"价格稳定在{rule.get('price_low')}到{rule.get('price_high')}区间"]
        if "volume_ratio_lt" in rule:
            parts.append(f"量比 < {rule.get('volume_ratio_lt')}")
        if rule.get("require_lower_shadow"):
            parts.append("当日K线有下影线")
        if rule.get("require_next_day_no_new_low"):
            parts.append("今日不跌破前一交易日低点")
        return "，且".join(parts)
    if rule_type == "range_rebound_fail":
        parts = [
            f"价格处于{rule.get('price_low')}到{rule.get('price_high')}区间",
            f"未突破{rule.get('fail_break_price')}",
        ]
        if "volume_ratio_lt" in rule:
            parts.append(f"量比 < {rule.get('volume_ratio_lt')}")
        return "，且".join(parts)
    return f"未知规则类型 {rule_type}"


def _position_condition_text(condition: Any) -> str:
    if not condition:
        return ""
    labels = {
        "current_position_shares_gt": "当前持仓 >",
        "current_position_shares_gte": "当前持仓 >=",
        "current_position_shares_lt": "当前持仓 <",
        "current_position_shares_lte": "当前持仓 <=",
        "current_position_shares_eq": "当前持仓 =",
    }
    if not isinstance(condition, dict):
        return "仓位条件格式非法"
    return "，".join(f"{labels.get(key, key)} {value}股" for key, value in condition.items())


def _explain_block_rules(block_rules: list[Any]) -> list[str]:
    if not block_rules:
        return ["- 无"]
    lines: list[str] = []
    for rule in block_rules:
        if isinstance(rule, str):
            lines.append(f"- {rule}")
        elif isinstance(rule, dict):
            desc = rule.get("description") or rule.get("explanation_template") or rule.get("id") or str(rule)
            lines.append(f"- {desc}")
        else:
            lines.append(f"- {rule}")
    return lines


def _explain_position(stock: dict[str, Any]) -> list[str]:
    items = [
        f"- 当前持仓：{stock.get('current_position_shares', 0)}股",
        f"- 最大持仓：{stock.get('max_position_shares', '未设置')}股",
        f"- 最大投入金额：{stock.get('max_invest_amount', '未设置')}",
        f"- 最小交易单位：{stock.get('min_lot', 100)}股",
    ]
    if "base_position_shares" in stock:
        items.append(f"- 底仓：{stock.get('base_position_shares')}股，卖出规则未设置 keep_min_shares 时默认保留底仓")
    if "t_position_shares" in stock:
        items.append(f"- T仓：{stock.get('t_position_shares')}股")
    if "t_cash_budget" in stock:
        items.append(f"- T仓现金预算：{stock.get('t_cash_budget')}")
    return items
