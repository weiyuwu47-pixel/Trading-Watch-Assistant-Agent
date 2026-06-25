from __future__ import annotations


RULE_REQUIRED_FIELDS: dict[str, set[str]] = {
    "breakout_recent_high": {"lookback_days"},
    "pullback_ma": {"ma", "tolerance_pct"},
    "break_ma": {"ma"},
    "far_above_ma": {"ma", "distance_pct_gt"},
    "reclaim_price_level": {"price_gte"},
    "break_price_level": {"price_gt"},
    "break_price_level_down": {"price_lt"},
    "stabilize_in_price_range": {"price_low", "price_high"},
    "range_rebound_fail": {"price_low", "price_high", "fail_break_price"},
}

SUPPORTED_RULE_TYPES = set(RULE_REQUIRED_FIELDS)

POSITION_CONDITION_FIELDS = {
    "current_position_shares_gt",
    "current_position_shares_gte",
    "current_position_shares_lt",
    "current_position_shares_lte",
    "current_position_shares_eq",
}

BLOCK_BUY_REQUIRED_FIELDS: dict[str, set[str]] = {
    "block_buy_below_price_without_volume": {"price_lt", "volume_ratio_lt"},
    "block_buy_price_range_without_volume": {"price_low", "price_high", "volume_ratio_lt"},
}

SUPPORTED_BLOCK_BUY_TYPES = set(BLOCK_BUY_REQUIRED_FIELDS)
