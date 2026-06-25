from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import AppConfig, load_stock_configs
from app.llm.deepseek_provider import DeepSeekProvider
from app.market.base import MarketMode
from app.market.multi_source_provider import MultiSourceMarketProvider
from app.models import Signal
from app.notify.pushplus import ACTION_LABELS, PushPlusNotifier
from app.storage import Storage
from app.stock_utils import find_stock
from app.strategy.decision_guard import DecisionGuard
from app.strategy.market_metrics import build_market_metrics
from app.strategy.rule_engine import evaluate_signal
from app.strategy.scene_analyzer import SceneAnalyzer


PUSH_ACTIONS = {"buy", "sell", "hold", "review"}


@dataclass(slots=True)
class RunResult:
    status: str
    message: str
    signals: list[Signal]


def run_once(config: AppConfig, symbol: str | None = None, mode: MarketMode = "auto", decision_mode: str | None = None) -> RunResult:
    storage = Storage(config.db_path)
    storage.init_db()

    market_provider = MultiSourceMarketProvider()
    llm_provider = DeepSeekProvider(config.deepseek_api_key, config.deepseek_base_url, config.deepseek_model)
    scene_analyzer = SceneAnalyzer(llm_provider)
    decision_guard = DecisionGuard()
    notifier = PushPlusNotifier(
        token=config.pushplus_token,
        api_url=config.pushplus_api_url,
        normal_channel=config.pushplus_normal_channel,
        urgent_channel=config.pushplus_urgent_channel,
        enable_voice=config.pushplus_enable_voice,
        dry_run=config.pushplus_dry_run,
    )

    all_stocks = load_stock_configs(config.stock_config_path)
    if symbol:
        stock = find_stock(all_stocks, symbol)
        if stock is None:
            raise ValueError(f"未找到股票: {symbol}")
        if not stock.get("enabled", True):
            raise ValueError(f"{symbol} 当前 enabled=false，请先启用或保存启用后的策略再运行")
        stocks = [stock]
    else:
        stocks = [stock for stock in all_stocks if stock.get("enabled", True)]
    if len(stocks) > 5:
        print("配置股票超过 5 只，本次只处理前 5 只。")
        stocks = stocks[:5]

    signals: list[Signal] = []
    errors: list[str] = []

    for stock in stocks:
        symbol = str(stock.get("symbol", ""))
        try:
            market_data = market_provider.get_snapshot(stock, mode=mode)
            active_decision_mode = _resolve_decision_mode(stock, decision_mode)
            if active_decision_mode == "hybrid":
                signal = _evaluate_hybrid_signal(stock, market_data, scene_analyzer, decision_guard)
            else:
                signal = evaluate_signal(stock, market_data)
                signal.raw_metrics["decision_mode"] = "rule"
                signal.reason = llm_provider.explain_signal(signal.to_dict(), stock)
            signal_id = storage.save_signal(signal, notified=False)
            signals.append(signal)

            should_push = signal.action in PUSH_ACTIONS
            duplicate = storage.has_notified_today(signal.symbol, signal.rule_id, signal.triggered_at)
            if should_push and not duplicate:
                if notifier.send(signal):
                    storage.mark_signal_notified(signal_id)
            elif should_push and duplicate:
                print(f"{signal.symbol} {signal.rule_id} 今日已推送，跳过重复提醒。")

            action_label = ACTION_LABELS.get(signal.action, signal.action)
            print(f"{signal.symbol} {action_label} {signal.shares}股 @ {signal.price}: {signal.reason}")
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            print(f"处理 {symbol} 失败: {exc}")

    if errors:
        status = "partial_success" if signals else "failed"
        message = "；".join(errors)
    else:
        status = "success"
        message = f"处理完成，共生成 {len(signals)} 条信号"
    storage.save_run(status=status, message=message, run_at=datetime.now().astimezone())
    return RunResult(status=status, message=message, signals=signals)


def signal_summary(signal: Signal) -> dict[str, Any]:
    return {
        "symbol": signal.symbol,
        "name": signal.name,
        "action": signal.action,
        "shares": signal.shares,
        "price": signal.price,
        "rule_id": signal.rule_id,
        "reason": signal.reason,
    }


def _resolve_decision_mode(stock: dict[str, Any], override: str | None) -> str:
    mode = str(override or stock.get("decision_mode") or "rule").lower()
    return mode if mode in {"rule", "hybrid"} else "rule"


def _evaluate_hybrid_signal(
    stock: dict[str, Any],
    market_data: Any,
    scene_analyzer: SceneAnalyzer,
    decision_guard: DecisionGuard,
) -> Signal:
    triggered_at = datetime.now().astimezone()
    symbol = str(stock.get("symbol", market_data.symbol))
    name = str(stock.get("name", symbol))
    metrics = build_market_metrics(market_data)

    if not market_data.ok:
        return Signal(
            symbol=symbol,
            name=name,
            action="review",
            shares=0,
            price=market_data.price,
            rule_id="market_error",
            reason=f"行情数据异常：{market_data.error}",
            triggered_at=triggered_at,
            raw_metrics=metrics | {"decision_mode": "hybrid", "error": market_data.error},
        )

    llm_decision = scene_analyzer.analyze(stock, market_data, metrics)
    guarded = decision_guard.guard(llm_decision, stock, market_data, metrics)
    action = guarded.get("action") if guarded.get("action") in {"buy", "sell", "hold", "review"} else "review"
    return Signal(
        symbol=symbol,
        name=name,
        action=action,  # type: ignore[arg-type]
        shares=int(guarded.get("shares", 0) or 0),
        price=market_data.price,
        rule_id=f"hybrid_{action}",
        reason=str(guarded.get("reason") or "hybrid mode 生成信号"),
        triggered_at=triggered_at,
        raw_metrics=metrics
        | {
            "decision_mode": "hybrid",
            "scene": guarded.get("scene"),
            "matched_strategy_clause": guarded.get("matched_strategy_clause"),
            "excluded_clauses": guarded.get("excluded_clauses"),
            "llm_confidence": guarded.get("confidence"),
            "needs_human_review": guarded.get("needs_human_review"),
            "guard_warnings": guarded.get("guard_warnings"),
            "raw_llm_decision": llm_decision,
        },
    )
