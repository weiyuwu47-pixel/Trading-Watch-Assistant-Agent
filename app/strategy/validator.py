from __future__ import annotations

from typing import Any

from app.strategy.schema import (
    BLOCK_BUY_REQUIRED_FIELDS,
    POSITION_CONDITION_FIELDS,
    RULE_REQUIRED_FIELDS,
    SUPPORTED_BLOCK_BUY_TYPES,
    SUPPORTED_RULE_TYPES,
)


def validate_stocks(stocks: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for index, stock in enumerate(stocks, start=1):
        symbol = stock.get("symbol", f"第{index}只")
        errors.extend(_validate_stock(stock, str(symbol)))
    return errors


def _validate_stock(stock: dict[str, Any], symbol: str) -> list[str]:
    errors: list[str] = []
    for field in ["symbol", "market", "name", "enabled", "valid_until", "max_position_shares", "current_position_shares", "min_lot"]:
        if field not in stock:
            errors.append(f"{symbol}: 缺少股票字段 {field}")

    for optional_int in ["base_position_shares", "t_position_shares"]:
        if optional_int in stock and not isinstance(stock[optional_int], int):
            errors.append(f"{symbol}: {optional_int} 必须是 int")
        elif optional_int in stock and stock[optional_int] < 0:
            errors.append(f"{symbol}: {optional_int} 不能为负数")
    if "t_cash_budget" in stock and not isinstance(stock["t_cash_budget"], (int, float)):
        errors.append(f"{symbol}: t_cash_budget 必须是数字")
    elif "t_cash_budget" in stock and stock["t_cash_budget"] < 0:
        errors.append(f"{symbol}: t_cash_budget 不能为负数")
    for numeric_field in ["max_invest_amount", "max_position_shares", "current_position_shares", "cost_price"]:
        if numeric_field in stock and isinstance(stock[numeric_field], (int, float)) and stock[numeric_field] < 0:
            errors.append(f"{symbol}: {numeric_field} 不能为负数")
    if "min_lot" in stock and isinstance(stock["min_lot"], int) and stock["min_lot"] <= 0:
        errors.append(f"{symbol}: min_lot 必须大于 0")
    if "human_strategy_text" in stock and not isinstance(stock["human_strategy_text"], str):
        errors.append(f"{symbol}: human_strategy_text 必须是字符串")
    if "decision_mode" in stock and stock["decision_mode"] not in {"rule", "hybrid"}:
        errors.append(f"{symbol}: decision_mode 必须是 rule 或 hybrid")
    if "block_buy_rules" in stock and not isinstance(stock["block_buy_rules"], list):
        errors.append(f"{symbol}: block_buy_rules 必须是列表")
    elif "block_buy_rules" in stock:
        for rule in stock["block_buy_rules"]:
            errors.extend(_validate_block_buy_rule(symbol, rule))

    for group_name in ["buy_rules", "sell_rules"]:
        rules = stock.get(group_name) or []
        if not isinstance(rules, list):
            errors.append(f"{symbol}: {group_name} 必须是列表")
            continue
        for rule in rules:
            errors.extend(_validate_rule(symbol, group_name, rule))
    return errors


def _validate_rule(symbol: str, group_name: str, rule: Any) -> list[str]:
    if not isinstance(rule, dict):
        return [f"{symbol}: {group_name} 中存在非对象规则"]

    errors: list[str] = []
    rule_id = rule.get("id", "<missing id>")
    rule_type = rule.get("type")
    if not rule.get("id"):
        errors.append(f"{symbol}: {group_name} 规则缺少 id")
    if rule_type not in SUPPORTED_RULE_TYPES:
        errors.append(f"{symbol}: {group_name}.{rule_id} 未知 rule type: {rule_type}")
        return errors

    for field in RULE_REQUIRED_FIELDS[str(rule_type)]:
        if field not in rule:
            errors.append(f"{symbol}: {group_name}.{rule_id} 类型 {rule_type} 缺少必需字段 {field}")

    action = rule.get("action")
    expected_action = "buy" if group_name == "buy_rules" else "sell"
    if action and action != expected_action:
        errors.append(f"{symbol}: {group_name}.{rule_id} action={action} 与规则分组 {group_name} 不一致")
    if "shares" not in rule:
        errors.append(f"{symbol}: {group_name}.{rule_id} 缺少 shares")
    if "position_condition" in rule:
        errors.extend(_validate_position_condition(symbol, group_name, str(rule_id), rule["position_condition"]))
    return errors


def _validate_position_condition(symbol: str, group_name: str, rule_id: str, condition: Any) -> list[str]:
    if not isinstance(condition, dict):
        return [f"{symbol}: {group_name}.{rule_id} position_condition 必须是对象"]
    errors: list[str] = []
    for field, value in condition.items():
        if field not in POSITION_CONDITION_FIELDS:
            errors.append(f"{symbol}: {group_name}.{rule_id} position_condition 未知字段 {field}")
        if not isinstance(value, int):
            errors.append(f"{symbol}: {group_name}.{rule_id} position_condition.{field} 必须是 int")
    return errors


def _validate_block_buy_rule(symbol: str, rule: Any) -> list[str]:
    if isinstance(rule, str):
        return []
    if not isinstance(rule, dict):
        return [f"{symbol}: block_buy_rules 中存在非对象规则"]

    errors: list[str] = []
    rule_id = rule.get("id", "<missing id>")
    rule_type = rule.get("type")
    if not rule.get("id"):
        errors.append(f"{symbol}: block_buy_rules 规则缺少 id")
    if rule_type not in SUPPORTED_BLOCK_BUY_TYPES:
        errors.append(f"{symbol}: block_buy_rules.{rule_id} 未知 block buy type: {rule_type}")
        return errors
    for field in BLOCK_BUY_REQUIRED_FIELDS[str(rule_type)]:
        if field not in rule:
            errors.append(f"{symbol}: block_buy_rules.{rule_id} 类型 {rule_type} 缺少必需字段 {field}")
    return errors
