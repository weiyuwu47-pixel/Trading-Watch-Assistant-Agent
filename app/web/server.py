from __future__ import annotations

import json
import re
import shutil
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from app.config import AppConfig, PROJECT_ROOT, load_app_config, load_stock_configs
from app.llm.deepseek_provider import DeepSeekProvider
from app.market.multi_source_provider import MultiSourceMarketProvider
from app.scheduler import run_once
from app.storage import Storage
from app.stock_utils import find_stock
from app.strategy import indicators
from app.strategy.decision_guard import DecisionGuard
from app.strategy.explainer import explain_stock_strategy
from app.strategy.market_metrics import build_market_metrics
from app.strategy.scene_analyzer import SceneAnalyzer
from app.strategy.schema import SUPPORTED_BLOCK_BUY_TYPES
from app.strategy.validator import validate_stocks


WEB_DIR = Path(__file__).resolve().parent
app = FastAPI(title="personal-stock-watch-agent")
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")

run_lock = threading.Lock()
run_state: dict[str, Any] = {"running": False, "current_step": "空闲", "last_result": None}
scheduler: BackgroundScheduler | None = None


class ToggleRequest(BaseModel):
    symbol: str
    enabled: bool


class RunOnceRequest(BaseModel):
    symbol: str | None = None
    mode: str = "auto"
    decision_mode: str | None = None


class MarketTestRequest(BaseModel):
    symbol: str
    mode: str = "close"


class SceneTestRequest(BaseModel):
    symbol: str
    mode: str = "close"


class GenerateStrategyRequest(BaseModel):
    symbol: str
    name: str
    market: str = "A"
    position: dict[str, Any] = {}
    parsed: dict[str, Any] = {}
    natural_strategy_text: str


class SaveStrategyRequest(BaseModel):
    symbol: str
    yaml_text: str


class ParseStrategyRequest(BaseModel):
    symbol: str
    name: str | None = None
    market: str = "A"
    natural_strategy_text: str


class DraftStrategyRequest(BaseModel):
    symbol: str | None = None
    yaml_text: str
    natural_strategy_text: str | None = None


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    config = _safe_config()
    return {
        "deepseek_configured": bool(config.deepseek_api_key),
        "pushplus_configured": bool(config.pushplus_token),
        "scheduler_running": scheduler is not None and scheduler.running,
        "run_running": run_state["running"],
        "current_step": run_state["current_step"],
        "last_result": run_state["last_result"],
        "db_path": str(config.db_path),
        "stock_config_path": str(config.stock_config_path),
        "now": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


@app.get("/api/stocks")
def api_stocks() -> dict[str, Any]:
    config = _safe_config()
    return {"stocks": load_stock_configs(config.stock_config_path)}


@app.post("/api/stocks/toggle")
def api_toggle_stock(payload: ToggleRequest) -> dict[str, Any]:
    config = _safe_config()
    data = _load_stock_file(config.stock_config_path)
    stocks = data.get("stocks", [])
    stock = next((item for item in stocks if str(item.get("symbol")) == payload.symbol), None)
    if stock is None:
        raise HTTPException(status_code=404, detail=f"未找到股票: {payload.symbol}")
    stock["enabled"] = payload.enabled
    _write_stock_file(config.stock_config_path, data)
    return {"ok": True, "symbol": payload.symbol, "enabled": payload.enabled}


@app.post("/api/strategy/validate")
def api_validate_strategy() -> dict[str, Any]:
    config = _safe_config()
    stocks = load_stock_configs(config.stock_config_path)
    errors = validate_stocks(stocks)
    if errors:
        return {"ok": False, "output": "策略校验失败：\n" + "\n".join(f"- {item}" for item in errors)}
    return {"ok": True, "output": f"策略校验通过：共 {len(stocks)} 只股票"}


@app.get("/api/strategy/explain")
def api_explain_strategy(symbol: str = Query(...)) -> dict[str, Any]:
    stock = _find_stock(symbol)
    return {"ok": True, "output": explain_stock_strategy(stock)}


@app.get("/api/strategy/compare")
def api_compare_strategy(symbol: str = Query(...)) -> dict[str, Any]:
    config = _safe_config()
    stock = _find_stock(symbol)
    summary = explain_stock_strategy(stock)
    human_text = str(stock.get("human_strategy_text") or "").strip()
    if not human_text:
        return {"ok": False, "output": "该股票未配置 human_strategy_text，无法做语义对比。\n\n" + summary}
    if not config.deepseek_api_key:
        return {"ok": False, "output": "未配置 DEEPSEEK_API_KEY，请人工核对：\n\n" + summary}

    provider = DeepSeekProvider(config.deepseek_api_key, config.deepseek_base_url, config.deepseek_model, timeout=30)
    result = provider.complete_text("你是交易策略语义校验助手，只比较文本含义，不给投资建议。", _compare_prompt(human_text, summary), max_tokens=900)
    if not result:
        return {"ok": False, "output": "DeepSeek 不可用，请人工核对：\n\n" + summary}
    return {"ok": True, "output": result}


@app.post("/api/strategy/validate_draft")
def api_validate_draft(payload: DraftStrategyRequest) -> dict[str, Any]:
    config = _safe_config()
    new_stock = _parse_stock_yaml(payload.yaml_text)
    next_stocks = _merge_draft_stock(config.stock_config_path, new_stock)
    errors = validate_stocks(next_stocks)
    if errors:
        return {"ok": False, "output": "YAML 草稿校验失败：\n" + "\n".join(f"- {item}" for item in errors)}
    return {"ok": True, "output": f"YAML 草稿校验通过：{new_stock.get('name', '')} {new_stock.get('symbol', '')}"}


@app.post("/api/strategy/explain_draft")
def api_explain_draft(payload: DraftStrategyRequest) -> dict[str, Any]:
    stock = _parse_stock_yaml(payload.yaml_text)
    return {"ok": True, "output": explain_stock_strategy(stock)}


@app.post("/api/strategy/compare_draft")
def api_compare_draft(payload: DraftStrategyRequest) -> dict[str, Any]:
    config = _safe_config()
    stock = _parse_stock_yaml(payload.yaml_text)
    summary = explain_stock_strategy(stock)
    human_text = str(payload.natural_strategy_text or stock.get("human_strategy_text") or "").strip()
    if not human_text:
        return {"ok": False, "output": "当前草稿缺少 human_strategy_text，无法做语义对比。\n\n" + summary}
    if not config.deepseek_api_key:
        return {"ok": False, "output": "未配置 DEEPSEEK_API_KEY，请人工核对：\n\n" + summary}

    provider = DeepSeekProvider(config.deepseek_api_key, config.deepseek_base_url, config.deepseek_model, timeout=30)
    result = provider.complete_text("你是交易策略语义校验助手，只比较文本含义，不给投资建议。", _compare_prompt(human_text, summary), max_tokens=900)
    if not result:
        return {"ok": False, "output": "DeepSeek 不可用，请人工核对：\n\n" + summary}
    return {"ok": True, "output": result}


@app.post("/api/run_once")
def api_run_once(payload: RunOnceRequest) -> dict[str, Any]:
    if payload.mode not in {"auto", "realtime", "close"}:
        raise HTTPException(status_code=400, detail="mode 必须是 auto/realtime/close")
    if payload.decision_mode is not None and payload.decision_mode not in {"rule", "hybrid"}:
        raise HTTPException(status_code=400, detail="decision_mode 必须是 rule/hybrid")
    if not run_lock.acquire(blocking=False):
        return {"ok": False, "message": "已有任务正在运行"}

    run_state.update({"running": True, "current_step": "执行 run_once：读取行情 / 执行决策 / 调用 DeepSeek / 发送 PushPlus / 写入 SQLite"})
    try:
        result = run_once(_safe_config(), symbol=payload.symbol, mode=payload.mode, decision_mode=payload.decision_mode)  # type: ignore[arg-type]
        signal = result.signals[-1].to_dict() if result.signals else None
        response = {
            "ok": result.status in {"success", "partial_success"},
            "action": signal.get("action") if signal else None,
            "message": result.message,
            "signal": signal,
        }
        run_state["last_result"] = response
        return response
    except ValueError as exc:
        response = {"ok": False, "message": str(exc), "signal": None}
        run_state["last_result"] = response
        return response
    except Exception as exc:
        run_state["last_result"] = {"ok": False, "message": str(exc)}
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        run_state.update({"running": False, "current_step": "空闲"})
        run_lock.release()


@app.get("/api/signals/recent")
def api_recent_signals() -> dict[str, Any]:
    config = _safe_config()
    storage = Storage(config.db_path)
    storage.init_db()
    rows = storage.latest_signals(20)
    signals = []
    for row in rows:
        raw = _parse_json(row.get("raw_metrics_json"))
        row["market_source"] = raw.get("market_source")
        row["trade_date"] = raw.get("trade_date")
        row["is_realtime"] = raw.get("is_realtime")
        row["raw_metrics"] = raw
        signals.append(row)
    return {"signals": signals}


@app.post("/api/market/test")
def api_market_test(payload: MarketTestRequest) -> dict[str, Any]:
    if payload.mode not in {"auto", "realtime", "close"}:
        raise HTTPException(status_code=400, detail="mode 必须是 auto/realtime/close")
    stock = _find_stock(payload.symbol)
    snapshot = MultiSourceMarketProvider().get_snapshot(stock, mode=payload.mode)  # type: ignore[arg-type]
    history = snapshot.daily_bars
    return {
        "symbol": snapshot.symbol,
        "name": snapshot.name,
        "price": snapshot.price,
        "open": snapshot.open,
        "high": snapshot.high,
        "low": snapshot.low,
        "close": snapshot.close,
        "volume": snapshot.volume,
        "amount": snapshot.amount,
        "trade_date": snapshot.trade_date,
        "source": snapshot.source,
        "is_realtime": snapshot.is_realtime,
        "ma5": indicators.ma(history, 5),
        "ma10": indicators.ma(history, 10),
        "ma20": indicators.ma(history, 20),
        "volume_ratio": indicators.volume_ratio(history, 5),
        "recent_high_10d": indicators.recent_high(history, 10),
        "recent_low_10d": indicators.recent_low(history, 10),
        "provider_errors": snapshot.provider_errors,
        "error": snapshot.error,
    }


@app.post("/api/scene/test")
def api_scene_test(payload: SceneTestRequest) -> dict[str, Any]:
    if payload.mode not in {"auto", "realtime", "close"}:
        raise HTTPException(status_code=400, detail="mode 必须是 auto/realtime/close")
    stock = _find_stock(payload.symbol)
    snapshot = MultiSourceMarketProvider().get_snapshot(stock, mode=payload.mode)  # type: ignore[arg-type]
    metrics = build_market_metrics(snapshot)
    raw_decision = SceneAnalyzer().analyze(stock, snapshot, metrics)
    guarded = DecisionGuard().guard(raw_decision, stock, snapshot, metrics)
    return {
        "ok": True,
        "symbol": stock.get("symbol"),
        "name": stock.get("name"),
        "price": snapshot.price,
        "market_source": snapshot.source,
        "trade_date": snapshot.trade_date,
        "is_realtime": snapshot.is_realtime,
        "raw_llm_decision": raw_decision,
        "guarded_decision": guarded,
        "provider_errors": snapshot.provider_errors,
        "market_error": snapshot.error,
    }


@app.post("/api/strategy/generate")
def api_generate_strategy(payload: GenerateStrategyRequest) -> dict[str, Any]:
    config = _safe_config()
    if not config.deepseek_api_key:
        return {"ok": False, "yaml_text": "", "message": "未配置 DeepSeek API Key，无法生成策略草稿"}

    provider = DeepSeekProvider(config.deepseek_api_key, config.deepseek_base_url, config.deepseek_model, timeout=45)
    text = provider.complete_text(
        "你是本地股票盯盘策略编译助手，只输出 JSON，不提供投资建议。",
        _generate_prompt(payload),
        max_tokens=2200,
    )
    if not text:
        return {"ok": False, "yaml_text": "", "message": "DeepSeek 生成失败，请手工编写 YAML"}

    generated = _extract_json_object(text)
    if not generated:
        try:
            generated = _parse_stock_yaml(text)
        except HTTPException:
            return {
                "ok": False,
                "yaml_text": "",
                "message": "DeepSeek 返回内容不是可解析的 JSON/YAML，请重新点击生成或人工整理策略",
            }

    stock = _normalize_generated_stock(payload, generated)
    yaml_text = yaml.safe_dump(stock, allow_unicode=True, sort_keys=False)
    errors = validate_stocks([stock])
    try:
        explanation = explain_stock_strategy(stock)
    except Exception as exc:
        explanation = f"反译失败，请人工检查 YAML：{exc}"

    if errors:
        return {
            "ok": False,
            "yaml_text": yaml_text,
            "explanation": explanation,
            "validation_errors": errors,
            "message": "已生成格式正确的 YAML 草稿，但策略字段校验未通过，请按错误提示修正后再保存",
        }
    return {"ok": True, "yaml_text": yaml_text, "explanation": explanation, "message": "已生成格式正确的 YAML 草稿，请人工确认后再保存"}


@app.post("/api/strategy/parse")
def api_parse_strategy(payload: ParseStrategyRequest) -> dict[str, Any]:
    _ensure_symbol_and_text(payload.symbol, payload.natural_strategy_text)
    config = _safe_config()
    parsed: dict[str, Any] = {}
    warnings: list[str] = []

    if config.deepseek_api_key:
        provider = DeepSeekProvider(config.deepseek_api_key, config.deepseek_base_url, config.deepseek_model, timeout=30)
        result = provider.complete_text(
            "你是本地股票策略字段抽取助手，只输出 JSON，不做交易判断。",
            _parse_prompt(payload),
            max_tokens=900,
        )
        if result:
            parsed = _extract_json_object(result)
        else:
            warnings.append("DeepSeek 解析失败，已使用本地保守抽取")
    else:
        warnings.append("未配置 DeepSeek，已使用本地保守抽取")

    parsed = _normalize_parsed_strategy(payload, parsed, warnings)
    return {"ok": True, "parsed": parsed}


@app.post("/api/strategy/save")
def api_save_strategy(payload: SaveStrategyRequest) -> dict[str, Any]:
    config = _safe_config()
    new_stock = _parse_stock_yaml(payload.yaml_text)
    if str(new_stock.get("symbol")) != payload.symbol:
        raise HTTPException(status_code=400, detail="请求 symbol 与 YAML 中 symbol 不一致")

    data = _load_stock_file(config.stock_config_path)
    old_stocks = data.get("stocks", [])
    if not isinstance(old_stocks, list):
        raise HTTPException(status_code=400, detail="stocks.yaml 格式错误：stocks 必须是列表")

    replaced = False
    next_stocks = []
    for stock in old_stocks:
        if str(stock.get("symbol")) == payload.symbol:
            next_stocks.append(new_stock)
            replaced = True
        else:
            next_stocks.append(stock)
    if not replaced:
        next_stocks.append(new_stock)

    errors = validate_stocks(next_stocks)
    if errors:
        return {"ok": False, "message": "保存前校验失败", "errors": errors}

    backup_path = _backup_stock_file(config.stock_config_path)
    _write_stock_file(config.stock_config_path, {"stocks": next_stocks})
    message = f"已保存，备份文件：{backup_path}"
    if new_stock.get("human_strategy_text"):
        message += "。建议继续运行语义对比。"
    return {"ok": True, "message": message}


@app.post("/api/scheduler/start")
def api_scheduler_start() -> dict[str, Any]:
    global scheduler
    if scheduler is not None and scheduler.running:
        return {"ok": True, "message": "后台监控已在运行"}
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    for hour, minute in [(11, 35), (14, 45), (15, 10)]:
        scheduler.add_job(_scheduled_run_once, "cron", hour=hour, minute=minute)
    scheduler.start()
    return {"ok": True, "message": "后台监控已启动：11:35、14:45、15:10"}


@app.post("/api/scheduler/stop")
def api_scheduler_stop() -> dict[str, Any]:
    global scheduler
    if scheduler is None or not scheduler.running:
        return {"ok": True, "message": "后台监控未运行"}
    scheduler.shutdown(wait=False)
    scheduler = None
    return {"ok": True, "message": "后台监控已停止"}


def _scheduled_run_once() -> None:
    if not run_lock.acquire(blocking=False):
        print("后台监控跳过：已有任务正在运行")
        return
    run_state.update({"running": True, "current_step": "后台监控执行中"})
    try:
        result = run_once(_safe_config(), mode="auto")
        run_state["last_result"] = {"ok": True, "message": result.message, "signals": [s.to_dict() for s in result.signals]}
    except Exception as exc:
        run_state["last_result"] = {"ok": False, "message": str(exc)}
        print(f"后台监控失败: {exc}")
    finally:
        run_state.update({"running": False, "current_step": "空闲"})
        run_lock.release()


def _safe_config() -> AppConfig:
    return replace(load_app_config(), pushplus_enable_voice=False)


def _find_stock(symbol: str) -> dict[str, Any]:
    config = _safe_config()
    stock = find_stock(load_stock_configs(config.stock_config_path), symbol)
    if stock is None:
        raise HTTPException(status_code=404, detail=f"未找到股票: {symbol}")
    return stock


def _load_stock_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "stocks" not in data:
        data["stocks"] = []
    return data


def _write_stock_file(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def _merge_draft_stock(path: Path, new_stock: dict[str, Any]) -> list[dict[str, Any]]:
    data = _load_stock_file(path)
    old_stocks = data.get("stocks", [])
    if not isinstance(old_stocks, list):
        raise HTTPException(status_code=400, detail="stocks.yaml 格式错误：stocks 必须是列表")

    symbol = str(new_stock.get("symbol"))
    replaced = False
    next_stocks: list[dict[str, Any]] = []
    for stock in old_stocks:
        if str(stock.get("symbol")) == symbol:
            next_stocks.append(new_stock)
            replaced = True
        else:
            next_stocks.append(stock)
    if not replaced:
        next_stocks.append(new_stock)
    return next_stocks


def _backup_stock_file(path: Path) -> Path:
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"stocks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml"
    shutil.copy2(path, backup_path)
    return backup_path


def _parse_stock_yaml(yaml_text: str) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"YAML 解析失败: {exc}") from exc
    if isinstance(parsed, dict) and "stocks" in parsed:
        stocks = parsed["stocks"]
        if isinstance(stocks, list) and len(stocks) == 1 and isinstance(stocks[0], dict):
            _validate_non_negative_stock(stocks[0])
            return stocks[0]
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
        _validate_non_negative_stock(parsed[0])
        return parsed[0]
    if isinstance(parsed, dict) and "symbol" in parsed:
        _validate_non_negative_stock(parsed)
        return parsed
    raise HTTPException(status_code=400, detail="YAML 必须是单个股票策略块，或只包含一个 stocks 条目")


def _parse_json(value: Any) -> dict[str, Any]:
    try:
        return json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _strip_yaml_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _ensure_symbol_and_text(symbol: str, natural_strategy_text: str) -> None:
    if not symbol.strip():
        raise HTTPException(status_code=400, detail="股票代码不能为空")
    if not natural_strategy_text.strip():
        raise HTTPException(status_code=400, detail="自然语言策略不能为空")


def _parse_prompt(payload: ParseStrategyRequest) -> str:
    default_valid_until = (datetime.now().date() + timedelta(days=7)).isoformat()
    return f"""
请从自然语言策略中抽取股票配置字段，只输出 JSON 对象，不要 markdown。
不要生成买卖判断，不要编造自然语言里没有的信息。
规则：
- “4万元T仓子弹”是 t_cash_budget，不是 max_invest_amount。
- “7800股底仓”是 current_position_shares 和 base_position_shares，不是 max_position_shares。
- “买入1000股T仓”是规则 shares，不是当前持仓。
- “最大投入16.5万”解析为 max_invest_amount=165000。
- “成本16.06”解析为 cost_price=16.06。
- 无法确定的字段填 null，并放入 missing_fields 或 warnings。

字段：
symbol, name, market, max_invest_amount, max_position_shares, current_position_shares,
base_position_shares, t_position_shares, t_cash_budget, cost_price, min_lot,
valid_until, strategy_style, missing_fields, warnings

默认 valid_until 可参考 {default_valid_until}，但如果原文有“未来2-3天”等短期策略，可推算更短有效期。

输入：
symbol={payload.symbol}
name={payload.name or ""}
market={payload.market}
natural_strategy_text={payload.natural_strategy_text}
""".strip()


def _normalize_parsed_strategy(payload: ParseStrategyRequest, parsed: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    text = payload.natural_strategy_text
    local = _local_extract_strategy_fields(text)
    merged = dict(parsed or {})
    for key, value in local.items():
        if value is not None:
            merged[key] = value

    missing_fields = list(merged.get("missing_fields") or [])
    merged_warnings = list(merged.get("warnings") or []) + warnings
    default_valid_until = (datetime.now().date() + timedelta(days=7)).isoformat()

    normalized = {
        "symbol": payload.symbol.strip(),
        "name": (payload.name or merged.get("name") or payload.symbol).strip(),
        "market": payload.market or merged.get("market") or "A",
        "max_invest_amount": _non_negative_number(merged.get("max_invest_amount"), "max_invest_amount", missing_fields, merged_warnings, default=0),
        "max_position_shares": _non_negative_int(merged.get("max_position_shares"), "max_position_shares", missing_fields, merged_warnings, default=0),
        "current_position_shares": _non_negative_int(merged.get("current_position_shares"), "current_position_shares", missing_fields, merged_warnings, default=0),
        "base_position_shares": _non_negative_int(merged.get("base_position_shares"), "base_position_shares", missing_fields, merged_warnings, default=None),
        "t_position_shares": _non_negative_int(merged.get("t_position_shares"), "t_position_shares", missing_fields, merged_warnings, default=0),
        "t_cash_budget": _non_negative_number(merged.get("t_cash_budget"), "t_cash_budget", missing_fields, merged_warnings, default=0),
        "cost_price": _non_negative_number(merged.get("cost_price"), "cost_price", missing_fields, merged_warnings, default=0),
        "min_lot": _non_negative_int(merged.get("min_lot"), "min_lot", missing_fields, merged_warnings, default=100),
        "valid_until": merged.get("valid_until") or default_valid_until,
        "strategy_style": merged.get("strategy_style") or "natural_language_strategy",
    }

    if normalized["base_position_shares"] is None:
        normalized["base_position_shares"] = normalized["current_position_shares"]

    if normalized["max_position_shares"] == 0 and normalized["max_invest_amount"] and normalized["cost_price"]:
        normalized["max_position_shares"] = int(normalized["max_invest_amount"] // normalized["cost_price"] // normalized["min_lot"] * normalized["min_lot"])
        if "max_position_shares" in missing_fields:
            missing_fields.remove("max_position_shares")
        merged_warnings.append("max_position_shares 未明确给出，已按 max_invest_amount / cost_price 粗略估算")

    for field in ["max_invest_amount", "max_position_shares"]:
        if not normalized[field] and field not in missing_fields:
            missing_fields.append(field)
            merged_warnings.append(f"{field} 未在自然语言中明确提到，需要确认")

    for defaulted_field in ["min_lot", "t_position_shares"]:
        if defaulted_field in missing_fields:
            missing_fields.remove(defaulted_field)

    merged_warnings = [
        item
        for item in merged_warnings
        if "当前T仓" not in str(item)
        and "T仓股数" not in str(item)
        and not ("最大持仓" in str(item) and normalized["max_position_shares"])
    ]
    normalized["missing_fields"] = sorted(set(missing_fields))
    normalized["warnings"] = list(dict.fromkeys(str(item) for item in merged_warnings if item))
    return normalized


def _local_extract_strategy_fields(text: str) -> dict[str, Any]:
    base = _first_number(text, [r"(\d+)\s*股底仓", r"底仓\s*(\d+)\s*股"])
    max_invest = _money_value(text, [r"最大投入\s*([0-9.]+)\s*万?", r"最大投入金额\s*([0-9.]+)\s*万?"])
    t_cash = _money_value(text, [r"([0-9.]+)\s*万\s*(?:元)?(?:作为)?T仓子弹", r"T仓子弹[^0-9]*([0-9.]+)\s*万"])
    cost = _first_float(text, [r"成本\s*([0-9.]+)", r"成本价\s*([0-9.]+)"])
    return {
        "current_position_shares": base,
        "base_position_shares": base,
        "cost_price": cost,
        "max_invest_amount": max_invest,
        "t_cash_budget": t_cash,
        "min_lot": 100,
        "t_position_shares": 0,
    }


def _first_number(text: str, patterns: list[str]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return int(float(match.group(1)))
    return None


def _first_float(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return float(match.group(1))
    return None


def _money_value(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = float(match.group(1))
            return value * 10000
    return None


def _non_negative_number(value: Any, field: str, missing_fields: list[str], warnings: list[str], default: float | None) -> float | None:
    if value in (None, ""):
        if field not in missing_fields:
            missing_fields.append(field)
        return default
    number = float(value)
    if number < 0:
        warnings.append(f"{field} 不能为负数，已重置为 {default}")
        return default
    return number


def _non_negative_int(value: Any, field: str, missing_fields: list[str], warnings: list[str], default: int | None) -> int | None:
    number = _non_negative_number(value, field, missing_fields, warnings, default)
    if number is None:
        return None
    return int(number)


def _validate_non_negative_stock(stock: dict[str, Any]) -> None:
    for field in ["max_invest_amount", "max_position_shares", "current_position_shares", "base_position_shares", "t_position_shares", "t_cash_budget", "cost_price"]:
        if field in stock and stock[field] is not None and float(stock[field]) < 0:
            raise HTTPException(status_code=400, detail=f"{field} 不能为负数")
    if int(stock.get("min_lot", 100) or 0) <= 0:
        raise HTTPException(status_code=400, detail="min_lot 必须大于 0")


def _normalize_generated_stock(payload: GenerateStrategyRequest, generated: dict[str, Any]) -> dict[str, Any]:
    parsed = payload.parsed or payload.position or {}
    if isinstance(generated.get("stocks"), list) and generated["stocks"] and isinstance(generated["stocks"][0], dict):
        generated = generated["stocks"][0]
    stock = dict(generated or {})
    now_plus_week = (datetime.now().date() + timedelta(days=7)).isoformat()

    normalized: dict[str, Any] = {
        "symbol": str(stock.get("symbol") or payload.symbol).strip(),
        "market": stock.get("market") or payload.market or "A",
        "name": stock.get("name") or payload.name or payload.symbol,
        "enabled": bool(stock.get("enabled", True)),
        "valid_until": stock.get("valid_until") or parsed.get("valid_until") or now_plus_week,
        "max_invest_amount": _number_or_default(stock.get("max_invest_amount", parsed.get("max_invest_amount")), 0),
        "max_position_shares": _int_or_default(stock.get("max_position_shares", parsed.get("max_position_shares")), 0),
        "current_position_shares": _int_or_default(stock.get("current_position_shares", parsed.get("current_position_shares")), 0),
        "base_position_shares": _int_or_default(stock.get("base_position_shares", parsed.get("base_position_shares", parsed.get("current_position_shares"))), 0),
        "t_position_shares": _int_or_default(stock.get("t_position_shares", parsed.get("t_position_shares")), 0),
        "t_cash_budget": _number_or_default(stock.get("t_cash_budget", parsed.get("t_cash_budget")), 0),
        "cost_price": _number_or_default(stock.get("cost_price", parsed.get("cost_price")), 0),
        "min_lot": max(_int_or_default(stock.get("min_lot", parsed.get("min_lot")), 100), 1),
        "strategy_style": stock.get("strategy_style") or parsed.get("strategy_style") or "natural_language_strategy",
        "decision_mode": stock.get("decision_mode") if stock.get("decision_mode") in {"rule", "hybrid"} else parsed.get("decision_mode", "rule"),
        "human_strategy_text": stock.get("human_strategy_text") or payload.natural_strategy_text,
        "principles": stock.get("principles") or [
            "规则引擎决定买卖，不预测涨跌",
            "成本价只用于仓位和风险管理，不作为买卖理由",
            "信号不明确时默认不买",
        ],
        "buy_rules": [],
        "sell_rules": [],
        "block_buy_rules": [],
        "hold_rule": stock.get("hold_rule") if isinstance(stock.get("hold_rule"), dict) else {"explanation_template": "未触发预设买卖条件，默认不操作"},
    }

    rules = stock.get("rules")
    buy_rules = list(stock.get("buy_rules") or [])
    sell_rules = list(stock.get("sell_rules") or [])
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            action = rule.get("action")
            if action == "sell":
                sell_rules.append(rule)
            else:
                buy_rules.append(rule)

    normalized["buy_rules"] = [_normalize_rule(rule, "buy", index) for index, rule in enumerate(buy_rules, start=1) if isinstance(rule, dict)]
    normalized["sell_rules"] = [_normalize_rule(rule, "sell", index) for index, rule in enumerate(sell_rules, start=1) if isinstance(rule, dict)]
    normalized["block_buy_rules"] = [
        _normalize_block_buy_rule(rule, index)
        for index, rule in enumerate(stock.get("block_buy_rules") or stock.get("block_rules") or [], start=1)
        if isinstance(rule, (dict, str))
    ]
    return normalized


def _normalize_rule(rule: dict[str, Any], action: str, index: int) -> dict[str, Any]:
    normalized = dict(rule)
    if "type" not in normalized and "rule_type" in normalized:
        normalized["type"] = normalized.pop("rule_type")
    normalized.setdefault("id", f"{action}_rule_{index}")
    normalized["action"] = action
    if "shares" in normalized:
        normalized["shares"] = _int_or_default(normalized["shares"], 0)
    if "keep_min_shares" in normalized:
        normalized["keep_min_shares"] = _int_or_default(normalized["keep_min_shares"], 0)
    if "max_t_position_shares" in normalized:
        normalized["max_t_position_shares"] = _int_or_default(normalized["max_t_position_shares"], 0)
    if "position_condition" in normalized and not isinstance(normalized["position_condition"], dict):
        normalized.pop("position_condition")
    _infer_rule_fields_from_text(normalized, action)
    return normalized


def _normalize_block_buy_rule(rule: dict[str, Any] | str, index: int) -> dict[str, Any] | str:
    if isinstance(rule, str):
        return rule
    normalized = dict(rule)
    if "type" not in normalized and "rule_type" in normalized:
        normalized["type"] = normalized.pop("rule_type")
    normalized.setdefault("id", f"block_buy_rule_{index}")
    if normalized.get("type") not in SUPPORTED_BLOCK_BUY_TYPES:
        return normalized.get("description") or normalized.get("explanation_template") or str(normalized)
    return normalized


def _infer_rule_fields_from_text(rule: dict[str, Any], action: str) -> None:
    text = _rule_text(rule)
    price_range = _extract_first_price_range(text)
    rule_type = rule.get("type")

    if rule_type == "stabilize_in_price_range" and price_range:
        rule.setdefault("price_low", price_range[0])
        rule.setdefault("price_high", price_range[1])

    if action == "sell" and rule_type == "break_price_level" and price_range:
        rule["type"] = "range_rebound_fail"
        rule.setdefault("price_low", price_range[0])
        rule.setdefault("price_high", price_range[1])
        rule.setdefault("fail_break_price", price_range[1])
        if "放量不足" in text or "量不足" in text or "无量" in text:
            rule.setdefault("volume_ratio_lt", 1.0)

    if rule.get("type") == "range_rebound_fail" and price_range:
        rule.setdefault("price_low", price_range[0])
        rule.setdefault("price_high", price_range[1])
        rule.setdefault("fail_break_price", price_range[1])

    price = _extract_first_price(text)
    if rule.get("type") == "break_price_level" and "price_gt" not in rule and price is not None:
        rule["price_gt"] = price
    if rule.get("type") == "reclaim_price_level" and "price_gte" not in rule and price is not None:
        rule["price_gte"] = price
    if rule.get("type") == "break_price_level_down" and "price_lt" not in rule and price is not None:
        rule["price_lt"] = price


def _rule_text(rule: dict[str, Any]) -> str:
    return " ".join(str(rule.get(key) or "") for key in ["description", "explanation_template", "notes", "id"])


def _extract_first_price_range(text: str) -> tuple[float, float] | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:-|—|–|到|至|~)\s*([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return None
    low = float(match.group(1))
    high = float(match.group(2))
    return (min(low, high), max(low, high))


def _extract_first_price(text: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    return float(match.group(1)) if match else None


def _number_or_default(value: Any, default: float) -> float:
    if value in (None, ""):
        return default
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if not match:
            return default
        value = match.group(0)
    number = float(value)
    return number if number >= 0 else default


def _int_or_default(value: Any, default: int) -> int:
    return int(_number_or_default(value, float(default)))


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = _strip_yaml_fence(text)
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def _compare_prompt(human_text: str, yaml_summary: str) -> str:
    return f"""
请比较“原始自然语言策略”和“YAML反译摘要”是否语义一致。
输出：✅ 一致 / ⚠️ 部分不一致 / ❌ 严重不一致，并列出差异和建议修正。
只做语义校验，不要给投资建议，不要自动修正。

原始自然语言策略：
{human_text}

YAML反译摘要：
{yaml_summary}
""".strip()


def _generate_prompt(payload: GenerateStrategyRequest) -> str:
    return f"""
请把自然语言策略转换成 personal-stock-watch-agent 支持的单只股票策略 JSON 对象。
只能使用这些 rule type：
- reclaim_price_level
- break_price_level
- break_price_level_down
- stabilize_in_price_range
- range_rebound_fail
- breakout_recent_high
- pullback_ma
- break_ma
- far_above_ma

要求：
- 不要把价格位条件误译成均线条件。
- 不能表达的条件写入 needs_manual_review: true，并在 notes 中说明。
- 必须保留 human_strategy_text。
- 规则字段必须叫 type，不要使用 rule_type。
- 买入规则必须放在 buy_rules 数组中，卖出规则必须放在 sell_rules 数组中。
- 每条买卖规则必须包含 id、description、type、action、shares、explanation_template。
- block_buy_rules 只说明禁止买入条件，不生成买卖信号。
- 输出纯 JSON 对象，不要 markdown 代码围栏，不要 YAML，不要解释文字。

JSON 顶层字段示例：
{{
  "symbol": "600900",
  "market": "A",
  "name": "长江电力",
  "enabled": true,
  "valid_until": "2026-06-27",
  "max_invest_amount": 0,
  "max_position_shares": 0,
  "current_position_shares": 0,
  "base_position_shares": 0,
  "t_position_shares": 0,
  "t_cash_budget": 0,
  "cost_price": 0,
  "min_lot": 100,
  "strategy_style": "natural_language_strategy",
  "human_strategy_text": "原始策略全文",
  "principles": ["信号不明确时默认不买"],
  "buy_rules": [],
  "sell_rules": [],
  "block_buy_rules": [],
  "hold_rule": {{"explanation_template": "未触发预设买卖条件，默认不操作"}}
}}

股票信息：
symbol: {payload.symbol}
name: {payload.name}
market: {payload.market}
parsed: {payload.parsed or payload.position}

自然语言策略：
{payload.natural_strategy_text}
""".strip()


def main() -> None:
    uvicorn.run("app.web.server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
