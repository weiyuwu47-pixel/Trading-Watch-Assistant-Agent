from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.models import Signal


ACTION_LABELS = {
    "buy": "买入",
    "sell": "卖出",
    "hold": "不动",
    "review": "需要复核",
}

TITLE_PREFIXES = {
    "buy": "【买入提醒】",
    "sell": "【卖出提醒】",
    "hold": "【不动】",
    "review": "【需要复核】",
}


class PushPlusNotifier:
    def __init__(
        self,
        token: str,
        api_url: str = "https://www.pushplus.plus/send",
        normal_channel: str = "app",
        urgent_channel: str = "voice",
        enable_voice: bool = False,
        dry_run: bool = True,
        timeout: int = 10,
    ) -> None:
        self.token = token
        self.api_url = api_url
        self.normal_channel = normal_channel or "app"
        self.urgent_channel = urgent_channel or "voice"
        self.enable_voice = enable_voice
        self.dry_run = dry_run
        self.timeout = timeout

    def send_normal(self, title: str, content: str) -> bool:
        return self._send(title=title, content=content, channel=self.normal_channel)

    def send_voice(self, title: str, content: str) -> bool:
        return self._send(title=title, content=content, channel=self.urgent_channel)

    def notify_signal(self, signal: dict[str, Any] | Signal, explanation: str | None = None) -> bool:
        data = _signal_to_dict(signal)
        if explanation:
            data["reason"] = explanation

        title, content = self.format_signal_message(data)
        action = str(data.get("action", "hold"))
        ok = True

        if action in {"buy", "sell"}:
            if self.enable_voice:
                ok = self.send_voice(title, content) and ok
            else:
                print("PushPlus voice disabled: 买/卖信号未发送语音电话，仅发送普通消息。")
            ok = self.send_normal(title, content) and ok
            return ok

        return self.send_normal(title, content)

    def send(self, signal: Signal) -> bool:
        return self.notify_signal(signal, signal.reason)

    def format_signal_message(self, signal: dict[str, Any]) -> tuple[str, str]:
        action = str(signal.get("action", "hold"))
        symbol = str(signal.get("symbol", ""))
        name = str(signal.get("name", symbol))
        title = f"{TITLE_PREFIXES.get(action, '【通知】')}{name} {symbol}".strip()

        action_label = ACTION_LABELS.get(action, action)
        shares = int(signal.get("shares") or 0)
        if action in {"buy", "sell"}:
            action_line = f"动作：{action_label} {shares} 股"
        else:
            action_line = f"动作：{action_label}"

        price = signal.get("price")
        price_text = "-" if price is None else f"{float(price):.3f}"
        rule_id = signal.get("rule_id")
        rule_text = "无" if action == "hold" or not rule_id else str(rule_id)
        triggered_at = _format_triggered_at(signal.get("triggered_at"))
        reason = str(signal.get("reason") or "无")

        content = "\n".join(
            [
                action_line,
                f"理由：{reason}",
                f"当前价：{price_text}",
                f"触发规则：{rule_text}",
                f"时间：{triggered_at}",
            ]
        )
        return title, content

    def _send(self, title: str, content: str, channel: str) -> bool:
        payload = {
            "token": self.token,
            "title": title,
            "content": content,
            "channel": channel,
        }

        if self.dry_run:
            self._print_payload("[DRY RUN]", payload)
            return True

        if not self.token:
            self._print_payload("[NO TOKEN]", payload)
            return True

        try:
            import requests

            resp = requests.post(self.api_url, json=payload, timeout=self.timeout)
            body_summary = _summarize_text(resp.text)
            print(f"PushPlus status={resp.status_code}, body={body_summary}")

            try:
                data = resp.json()
            except ValueError:
                print("PushPlus warning: 响应不是 JSON")
                return False

            if int(data.get("code", 0)) != 200:
                print(f"PushPlus warning: code={data.get('code')}, msg={data.get('msg') or data.get('message')}")
                return False
            return True
        except Exception as exc:
            print(f"PushPlus warning: 请求失败，不影响主流程: {exc}")
            return False

    def _print_payload(self, prefix: str, payload: dict[str, Any]) -> None:
        safe_payload = dict(payload)
        if safe_payload.get("token"):
            safe_payload["token"] = "***"
        print(f"{prefix} PushPlus payload:")
        print(json.dumps(safe_payload, ensure_ascii=False, indent=2))


def _signal_to_dict(signal: dict[str, Any] | Signal) -> dict[str, Any]:
    if isinstance(signal, Signal):
        return signal.to_dict()
    return dict(signal)


def _format_triggered_at(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return value
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _summarize_text(text: str, limit: int = 300) -> str:
    compact = " ".join(text.replace("\n", " ").split())
    return compact[:limit]
