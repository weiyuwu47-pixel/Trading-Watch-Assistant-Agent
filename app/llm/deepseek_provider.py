from __future__ import annotations

import json
import re
from typing import Any

from app.llm.base import LLMProvider
from app.llm.template_provider import TemplateProvider


class DeepSeekProvider(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 10) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.fallback = TemplateProvider()

    def explain_signal(self, signal: dict[str, Any], stock_config: dict[str, Any]) -> str:
        if not self.api_key:
            return self.fallback.explain_signal(signal, stock_config)

        messages = [
            {"role": "system", "content": "你是个人盯盘纪律助手，只解释规则信号，不提供自由投资建议。"},
            {"role": "user", "content": self._build_prompt(signal, stock_config)},
        ]

        explanation = self._call_with_openai_sdk(messages)
        if explanation:
            return explanation

        explanation = self._call_with_requests(messages)
        if explanation:
            return explanation

        return self.fallback.explain_signal(signal, stock_config)

    def complete_text(self, system_prompt: str, user_prompt: str, max_tokens: int = 800) -> str | None:
        if not self.api_key:
            return None
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._call_with_openai_sdk(
            messages,
            max_tokens=max_tokens,
            max_chars=4000,
            preserve_newlines=True,
        ) or self._call_with_requests(
            messages,
            max_tokens=max_tokens,
            max_chars=4000,
            preserve_newlines=True,
        )

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 800) -> dict[str, Any]:
        if not self.api_key:
            return _review_json("未配置 DEEPSEEK_API_KEY")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        content = self._call_with_openai_sdk(
            messages,
            max_tokens=max_tokens,
            max_chars=8000,
            preserve_newlines=True,
            response_format={"type": "json_object"},
        ) or self._call_with_requests(
            messages,
            max_tokens=max_tokens,
            max_chars=8000,
            preserve_newlines=True,
            response_format={"type": "json_object"},
        ) or self._call_with_openai_sdk(
            messages,
            max_tokens=max_tokens,
            max_chars=8000,
            preserve_newlines=True,
        ) or self._call_with_requests(
            messages,
            max_tokens=max_tokens,
            max_chars=8000,
            preserve_newlines=True,
        )
        if not content:
            return _review_json("DeepSeek JSON 调用失败")
        return _parse_json_object(content)

    def _call_with_openai_sdk(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 200,
        max_chars: int = 180,
        preserve_newlines: bool = False,
        response_format: dict[str, str] | None = None,
    ) -> str | None:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "temperature": 0.2,
                "max_tokens": max_tokens,
                "extra_body": {"thinking": {"type": "disabled"}},
            }
            if response_format:
                kwargs["response_format"] = response_format
            response = client.chat.completions.create(
                **kwargs,  # type: ignore[arg-type]
            )
            content = response.choices[0].message.content
            return self._normalize_explanation(content, max_chars=max_chars, preserve_newlines=preserve_newlines)
        except Exception:
            return None

    def _call_with_requests(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 200,
        max_chars: int = 180,
        preserve_newlines: bool = False,
        response_format: dict[str, str] | None = None,
    ) -> str | None:
        try:
            import requests

            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": max_tokens,
                "stream": False,
                "thinking": {"type": "disabled"},
            }
            if response_format:
                payload["response_format"] = response_format
            response = requests.post(
                self._chat_completions_url(),
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            return self._normalize_explanation(content, max_chars=max_chars, preserve_newlines=preserve_newlines)
        except Exception:
            return None

    def _chat_completions_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _normalize_explanation(self, content: Any, max_chars: int = 180, preserve_newlines: bool = False) -> str | None:
        raw = str(content or "").strip()
        if preserve_newlines:
            explanation = "\n".join(" ".join(line.split()) for line in raw.splitlines()).strip()
        else:
            explanation = " ".join(raw.replace("\n", " ").split())
        return explanation[:max_chars] or None

    def _build_prompt(self, signal: dict[str, Any], stock_config: dict[str, Any]) -> str:
        principles = "；".join(str(item) for item in stock_config.get("principles", []))
        return f"""
请基于以下规则引擎结果，只生成一句中文解释。

硬性要求：
1. 不要编造行情，不要加入输入之外的数据。
2. 不要改变 action 和 shares，不要建议其他股数。
3. 只输出一句中文解释，不要列表，不要免责声明。
4. 不以回本、盈利目标、怕踏空作为买卖理由。
5. 尊重盘面，信号不明确时默认不买。
6. 如果 action 是 hold，要解释为什么不操作。

股票：{signal.get("name")} {signal.get("symbol")}
规则结果 action：{signal.get("action")}
规则结果 shares：{signal.get("shares")}
当前价：{signal.get("price")}
触发规则：{signal.get("rule_id")}
规则原始理由：{signal.get("reason")}
关键指标：{signal.get("raw_metrics")}
用户原则：{principles}
""".strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else _review_json("DeepSeek 返回 JSON 不是对象")
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            return _review_json("DeepSeek 返回内容无法解析为 JSON")
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else _review_json("DeepSeek 返回 JSON 不是对象")
        except json.JSONDecodeError:
            return _review_json("DeepSeek 返回内容无法解析为 JSON")


def _review_json(reason: str) -> dict[str, Any]:
    return {
        "action": "review",
        "shares": 0,
        "scene": "无法完成智能盘面理解",
        "matched_strategy_clause": "",
        "excluded_clauses": [],
        "reason": reason,
        "confidence": "low",
        "needs_human_review": True,
    }
