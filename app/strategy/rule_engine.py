from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.market.base import MarketSnapshot
from app.models import Signal
from app.strategy import indicators
from app.strategy.position_sizer import legal_buy_shares, legal_sell_shares
from app.strategy.schema import POSITION_CONDITION_FIELDS


def evaluate_signal(stock_config: dict[str, Any], market_data: MarketSnapshot, now: datetime | None = None) -> Signal:
    triggered_at = now or datetime.now().astimezone()
    symbol = str(stock_config.get("symbol", market_data.symbol))
    name = str(stock_config.get("name", symbol))

    if not stock_config.get("enabled", True):
        return _signal(symbol, name, "review", 0, market_data.price, "disabled", "股票配置已禁用，请复核", triggered_at, {"error": "disabled"})

    if _is_expired(stock_config.get("valid_until"), triggered_at.date()):
        return _signal(symbol, name, "review", 0, market_data.price, "strategy_expired", "策略有效期已过，请复核后再执行", triggered_at, {"valid_until": stock_config.get("valid_until")})

    if not market_data.ok:
        return _signal(
            symbol,
            name,
            "review",
            0,
            market_data.price,
            "market_error",
            f"行情数据异常：{market_data.error}",
            triggered_at,
            _market_meta(market_data) | {"error": market_data.error},
        )

    metrics = _build_metrics(market_data)
    price = float(market_data.price or 0)

    for rule in stock_config.get("sell_rules", []) or []:
        matched, rule_metrics = _match_rule(rule, price, market_data.daily_bars, metrics, stock_config)
        if matched:
            return _build_trade_signal(stock_config, market_data, rule, "sell", triggered_at, rule_metrics)

    for rule in stock_config.get("buy_rules", []) or []:
        matched, rule_metrics = _match_rule(rule, price, market_data.daily_bars, metrics, stock_config)
        if matched:
            return _build_trade_signal(stock_config, market_data, rule, "buy", triggered_at, rule_metrics)

    hold_reason = _build_hold_reason(stock_config, price, metrics)
    return _signal(symbol, name, "hold", 0, price, "hold", hold_reason, triggered_at, metrics)


def _is_expired(valid_until: Any, today: date) -> bool:
    if not valid_until:
        return False
    try:
        if isinstance(valid_until, date):
            valid_date = valid_until
        else:
            valid_date = date.fromisoformat(str(valid_until))
        return today > valid_date
    except ValueError:
        return True


def _build_metrics(market_data: MarketSnapshot) -> dict[str, Any]:
    history = market_data.daily_bars
    price = market_data.price
    ma_values = {f"ma{period}": indicators.ma(history, period) for period in (5, 10, 20)}
    metrics: dict[str, Any] = {
        "price": price,
        "volume": market_data.volume,
        "volume_ratio": indicators.volume_ratio(history, 5),
        **_market_meta(market_data),
        **ma_values,
    }
    for period, ma_value in ma_values.items():
        metrics[f"distance_pct_{period}"] = indicators.distance_pct(price, ma_value)
    return metrics


def _match_rule(
    rule: dict[str, Any],
    price: float,
    history: Any,
    base_metrics: dict[str, Any],
    stock_config: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    rule_type = rule.get("type")
    metrics = dict(base_metrics)

    position_matched, position_metrics = _match_position_condition(rule.get("position_condition"), stock_config)
    metrics.update(position_metrics)
    if not position_matched:
        return False, metrics

    if rule_type == "breakout_recent_high":
        lookback = int(rule.get("lookback_days", 10))
        high = indicators.recent_high(history, lookback)
        vr = metrics.get("volume_ratio")
        threshold = float(rule.get("volume_ratio_gt", 0))
        metrics.update({"recent_high": high, "lookback_days": lookback, "volume_ratio_gt": threshold})
        return high is not None and vr is not None and price > high and vr > threshold, metrics

    if rule_type == "pullback_ma":
        period = int(rule.get("ma", 5))
        ma_value = indicators.ma(history, period)
        dist = indicators.distance_pct(price, ma_value)
        vr = metrics.get("volume_ratio")
        tolerance = float(rule.get("tolerance_pct", 0))
        threshold = float(rule.get("volume_ratio_lt", 999))
        metrics.update({f"ma{period}": ma_value, "distance_pct": dist, "tolerance_pct": tolerance, "volume_ratio_lt": threshold})
        return dist is not None and vr is not None and abs(dist) <= tolerance and price >= float(ma_value or 0) and vr < threshold, metrics

    if rule_type == "break_ma":
        period = int(rule.get("ma", 10))
        ma_value = indicators.ma(history, period)
        metrics.update({f"ma{period}": ma_value})
        return ma_value is not None and price < ma_value, metrics

    if rule_type == "far_above_ma":
        period = int(rule.get("ma", 20))
        ma_value = indicators.ma(history, period)
        dist = indicators.distance_pct(price, ma_value)
        threshold = float(rule.get("distance_pct_gt", 0))
        metrics.update({f"ma{period}": ma_value, "distance_pct": dist, "distance_pct_gt": threshold})
        return dist is not None and dist > threshold, metrics

    if rule_type == "reclaim_price_level":
        threshold = float(rule.get("price_gte", 0))
        vr_threshold = rule.get("volume_ratio_gt")
        metrics.update({"price_gte": threshold, "volume_ratio_gt": vr_threshold})
        return price >= threshold and _optional_volume_gt(metrics.get("volume_ratio"), vr_threshold), metrics

    if rule_type == "break_price_level":
        threshold = float(rule.get("price_gt", 0))
        vr_threshold = rule.get("volume_ratio_gt")
        metrics.update({"price_gt": threshold, "volume_ratio_gt": vr_threshold})
        return price > threshold and _optional_volume_gt(metrics.get("volume_ratio"), vr_threshold), metrics

    if rule_type == "break_price_level_down":
        threshold = float(rule.get("price_lt", 0))
        metrics.update({"price_lt": threshold})
        return price < threshold, metrics

    if rule_type == "stabilize_in_price_range":
        low = float(rule.get("price_low", 0))
        high = float(rule.get("price_high", 0))
        vr_threshold = rule.get("volume_ratio_lt")
        require_lower_shadow = bool(rule.get("require_lower_shadow", False))
        require_next_day_no_new_low = bool(rule.get("require_next_day_no_new_low", False))
        lower_shadow_ok = _has_lower_shadow(history)
        no_new_low_ok = _has_no_new_low(history)
        metrics.update(
            {
                "price_low": low,
                "price_high": high,
                "volume_ratio_lt": vr_threshold,
                "require_lower_shadow": require_lower_shadow,
                "lower_shadow_ok": lower_shadow_ok,
                "require_next_day_no_new_low": require_next_day_no_new_low,
                "next_day_no_new_low_ok": no_new_low_ok,
            }
        )
        return (
            low <= price <= high
            and _optional_volume_lt(metrics.get("volume_ratio"), vr_threshold)
            and (not require_lower_shadow or lower_shadow_ok)
            and (not require_next_day_no_new_low or no_new_low_ok)
        ), metrics

    if rule_type == "range_rebound_fail":
        low = float(rule.get("price_low", 0))
        high = float(rule.get("price_high", 0))
        fail_break_price = float(rule.get("fail_break_price", 0))
        vr_threshold = rule.get("volume_ratio_lt")
        metrics.update(
            {
                "price_low": low,
                "price_high": high,
                "fail_break_price": fail_break_price,
                "volume_ratio_lt": vr_threshold,
            }
        )
        return low <= price <= high and price < fail_break_price and _optional_volume_lt(metrics.get("volume_ratio"), vr_threshold), metrics

    metrics["unsupported_rule_type"] = rule_type
    return False, metrics


def _build_trade_signal(
    stock_config: dict[str, Any],
    market_data: MarketSnapshot,
    rule: dict[str, Any],
    action: str,
    triggered_at: datetime,
    metrics: dict[str, Any],
) -> Signal:
    symbol = str(stock_config.get("symbol", market_data.symbol))
    name = str(stock_config.get("name", symbol))
    price = float(market_data.price or 0)
    min_lot = int(stock_config.get("min_lot", 100) or 100)
    requested = int(rule.get("shares", 0) or 0)
    reason = str(rule.get("explanation_template") or rule.get("description") or "触发预设规则")
    rule_id = str(rule.get("id", rule.get("type", action)))

    if action == "buy":
        shares = legal_buy_shares(
            requested_shares=requested,
            price=price,
            current_position_shares=int(stock_config.get("current_position_shares", 0) or 0),
            max_invest_amount=float(stock_config.get("max_invest_amount", 0) or 0),
            max_position_shares=int(stock_config.get("max_position_shares", 0) or 0),
            min_lot=min_lot,
        )
        max_t_position_shares = rule.get("max_t_position_shares")
        base_position_shares = stock_config.get("base_position_shares")
        if max_t_position_shares is not None and base_position_shares is not None:
            current_position = int(stock_config.get("current_position_shares", 0) or 0)
            current_t_position = max(0, current_position - int(base_position_shares or 0))
            remaining_t_shares = max(0, int(max_t_position_shares) - current_t_position)
            shares = min(shares, remaining_t_shares)
            shares = shares // min_lot * min_lot
        metrics.update({"requested_shares": requested, "sized_shares": shares})
        if shares <= 0:
            hold_reason = f"触发{rule_id}，但买入会超过资金或持仓上限，默认不买"
            return _signal(symbol, name, "hold", 0, price, rule_id, hold_reason, triggered_at, metrics)
        return _signal(symbol, name, "buy", shares, price, rule_id, reason, triggered_at, metrics)

    if action == "sell":
        shares = legal_sell_shares(
            requested_shares=requested,
            current_position_shares=int(stock_config.get("current_position_shares", 0) or 0),
            min_lot=min_lot,
            keep_min_shares=rule.get("keep_min_shares", stock_config.get("base_position_shares")),
        )
        metrics.update({"requested_shares": requested, "sized_shares": shares, "keep_min_shares": rule.get("keep_min_shares", stock_config.get("base_position_shares"))})
        if shares <= 0:
            hold_reason = f"触发{rule_id}，但卖出会低于底仓或无可卖持仓，默认不动"
            return _signal(symbol, name, "hold", 0, price, rule_id, hold_reason, triggered_at, metrics)
        return _signal(symbol, name, "sell", shares, price, rule_id, reason, triggered_at, metrics)

    return _signal(symbol, name, "review", 0, price, rule_id, "规则 action 非法，请复核", triggered_at, metrics)


def _signal(
    symbol: str,
    name: str,
    action: str,
    shares: int,
    price: float | None,
    rule_id: str,
    reason: str,
    triggered_at: datetime,
    metrics: dict[str, Any],
) -> Signal:
    return Signal(
        symbol=symbol,
        name=name,
        action=action,  # type: ignore[arg-type]
        shares=shares,
        price=price,
        rule_id=rule_id,
        reason=reason,
        triggered_at=triggered_at,
        raw_metrics=metrics,
    )


def _market_meta(market_data: MarketSnapshot) -> dict[str, Any]:
    return {
        "market_source": market_data.source,
        "is_realtime": market_data.is_realtime,
        "trade_date": market_data.trade_date,
        "provider_errors": market_data.provider_errors,
    }


def _match_position_condition(condition: Any, stock_config: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    if not condition:
        return True, {"position_condition_matched": True}
    if not isinstance(condition, dict):
        return False, {"position_condition_matched": False, "position_condition_error": "position_condition 必须是对象"}

    current = int(stock_config.get("current_position_shares", 0) or 0)
    checks = {
        "current_position_shares_gt": lambda expected: current > int(expected),
        "current_position_shares_gte": lambda expected: current >= int(expected),
        "current_position_shares_lt": lambda expected: current < int(expected),
        "current_position_shares_lte": lambda expected: current <= int(expected),
        "current_position_shares_eq": lambda expected: current == int(expected),
    }
    matched = True
    for field, expected in condition.items():
        if field not in POSITION_CONDITION_FIELDS:
            matched = False
            continue
        if not checks[field](expected):
            matched = False
    return matched, {"position_condition_matched": matched, "current_position_shares": current, "position_condition": condition}


def _optional_volume_gt(volume_ratio: Any, threshold: Any) -> bool:
    if threshold is None:
        return True
    return volume_ratio is not None and float(volume_ratio) > float(threshold)


def _optional_volume_lt(volume_ratio: Any, threshold: Any) -> bool:
    if threshold is None:
        return True
    return volume_ratio is not None and float(volume_ratio) < float(threshold)


def _has_lower_shadow(history: Any) -> bool:
    if history is None or not hasattr(history, "empty") or history.empty:
        return False
    latest = history.iloc[-1]
    low = float(latest.get("low", 0))
    open_price = float(latest.get("open", 0))
    close_price = float(latest.get("close", 0))
    return low < min(open_price, close_price)


def _has_no_new_low(history: Any) -> bool:
    if history is None or not hasattr(history, "empty") or history.empty or len(history) < 2:
        return False
    latest_low = float(history.iloc[-1].get("low", 0))
    previous_low = float(history.iloc[-2].get("low", 0))
    return latest_low >= previous_low


def _build_hold_reason(stock_config: dict[str, Any], price: float | None = None, metrics: dict[str, Any] | None = None) -> str:
    base_reason = (stock_config.get("hold_rule") or {}).get("explanation_template", "未触发预设买卖条件，默认不操作")
    block_rules = stock_config.get("block_buy_rules") or []
    if not block_rules:
        return str(base_reason)

    matched_reasons: list[str] = []
    descriptions: list[str] = []
    for rule in block_rules:
        if isinstance(rule, str):
            descriptions.append(rule)
        elif isinstance(rule, dict):
            reason = str(rule.get("explanation_template") or rule.get("description") or rule.get("id") or "禁止买入条件")
            if _match_block_buy_rule(rule, price, metrics or {}):
                matched_reasons.append(reason)
            descriptions.append(reason)
    if matched_reasons:
        return f"{base_reason}；{matched_reasons[0]}"
    if descriptions:
        return f"{base_reason}；禁止买入条件：{'；'.join(descriptions)}"
    return str(base_reason)


def _match_block_buy_rule(rule: dict[str, Any], price: float | None, metrics: dict[str, Any]) -> bool:
    if price is None:
        return False
    volume_ratio = metrics.get("volume_ratio")
    rule_type = rule.get("type")
    if rule_type == "block_buy_below_price_without_volume":
        return price < float(rule.get("price_lt", 0)) and _optional_volume_lt(volume_ratio, rule.get("volume_ratio_lt"))
    if rule_type == "block_buy_price_range_without_volume":
        low = float(rule.get("price_low", 0))
        high = float(rule.get("price_high", 0))
        return low <= price <= high and _optional_volume_lt(volume_ratio, rule.get("volume_ratio_lt"))
    return False
