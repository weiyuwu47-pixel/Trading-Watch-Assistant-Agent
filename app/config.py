from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dependency may not be installed before setup
    load_dotenv = None  # type: ignore[assignment]


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class AppConfig:
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    pushplus_token: str
    pushplus_api_url: str
    pushplus_normal_channel: str
    pushplus_urgent_channel: str
    pushplus_enable_voice: bool
    pushplus_dry_run: bool
    db_path: Path
    stock_config_path: Path


def _resolve_project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_app_config() -> AppConfig:
    env_path = PROJECT_ROOT / ".env"
    if load_dotenv is not None:
        load_dotenv(env_path)
    else:
        _load_env_file(env_path)
    return AppConfig(
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip(),
        pushplus_token=os.getenv("PUSHPLUS_TOKEN", "").strip(),
        pushplus_api_url=os.getenv("PUSHPLUS_API_URL", "https://www.pushplus.plus/send").strip(),
        pushplus_normal_channel=os.getenv("PUSHPLUS_NORMAL_CHANNEL", "app").strip() or "app",
        pushplus_urgent_channel=os.getenv("PUSHPLUS_URGENT_CHANNEL", "voice").strip() or "voice",
        pushplus_enable_voice=_parse_bool(os.getenv("PUSHPLUS_ENABLE_VOICE"), default=False),
        pushplus_dry_run=_parse_bool(os.getenv("PUSHPLUS_DRY_RUN"), default=True),
        db_path=_resolve_project_path(os.getenv("DB_PATH", "data/stock_watch.sqlite")),
        stock_config_path=_resolve_project_path(os.getenv("STOCK_CONFIG_PATH", "config/stocks.yaml")),
    )


def load_stock_configs(config_path: Path) -> list[dict[str, Any]]:
    try:
        import yaml
    except Exception as exc:
        raise RuntimeError("缺少 PyYAML，请先执行 pip install -r requirements.txt") from exc

    if not config_path.exists():
        raise FileNotFoundError(f"股票配置文件不存在: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        content = yaml.safe_load(f) or {}

    stocks = content.get("stocks", [])
    if not isinstance(stocks, list):
        raise ValueError("stocks.yaml 的 stocks 必须是列表")
    return [stock for stock in stocks if isinstance(stock, dict)]


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
