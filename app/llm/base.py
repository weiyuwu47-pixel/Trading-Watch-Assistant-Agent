from __future__ import annotations

from typing import Any


class LLMProvider:
    def explain_signal(self, signal: dict[str, Any], stock_config: dict[str, Any]) -> str:
        raise NotImplementedError
