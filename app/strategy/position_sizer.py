from __future__ import annotations


def floor_to_lot(shares: int, min_lot: int = 100) -> int:
    if min_lot <= 0:
        min_lot = 100
    return max(0, int(shares) // min_lot * min_lot)


def legal_buy_shares(
    requested_shares: int,
    price: float,
    current_position_shares: int,
    max_invest_amount: float,
    max_position_shares: int,
    min_lot: int = 100,
) -> int:
    requested = floor_to_lot(requested_shares, min_lot)
    if requested <= 0 or price <= 0:
        return 0

    remaining_shares = max(0, int(max_position_shares) - int(current_position_shares))
    remaining_by_amount = max(0, int((float(max_invest_amount) - int(current_position_shares) * price) // price))
    allowed = min(requested, remaining_shares, remaining_by_amount)
    return floor_to_lot(allowed, min_lot)


def legal_sell_shares(
    requested_shares: int,
    current_position_shares: int,
    min_lot: int = 100,
    keep_min_shares: int | None = None,
) -> int:
    requested = floor_to_lot(requested_shares, min_lot)
    if requested <= 0:
        return 0

    keep = int(keep_min_shares or 0)
    max_sell = max(0, int(current_position_shares) - keep)
    allowed = min(requested, max_sell)
    return floor_to_lot(allowed, min_lot)
