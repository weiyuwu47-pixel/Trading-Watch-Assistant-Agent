from __future__ import annotations

from typing import Any

from app.llm.base import LLMProvider


class TemplateProvider(LLMProvider):
    def explain_signal(self, signal: dict[str, Any], stock_config: dict[str, Any]) -> str:
        reason = str(signal.get("reason") or "").strip()
        if reason:
            return _one_sentence(reason)

        if signal.get("action") == "hold":
            return _one_sentence((stock_config.get("hold_rule") or {}).get("explanation_template", "未触发预设买卖条件，默认不操作"))
        return "触发预设规则，请按信号手动复核后操作。"


def _one_sentence(text: str) -> str:
    return " ".join(text.replace("\n", " ").split())[:180]
