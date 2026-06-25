from __future__ import annotations

import argparse
from datetime import datetime

from app.config import load_app_config
from app.notify.pushplus import PushPlusNotifier


def main() -> None:
    parser = argparse.ArgumentParser(description="测试 PushPlus 通知链路")
    parser.add_argument("--action", choices=["hold", "review", "buy", "sell"], required=True)
    args = parser.parse_args()

    config = load_app_config()
    notifier = PushPlusNotifier(
        token=config.pushplus_token,
        api_url=config.pushplus_api_url,
        normal_channel=config.pushplus_normal_channel,
        urgent_channel=config.pushplus_urgent_channel,
        enable_voice=config.pushplus_enable_voice,
        dry_run=config.pushplus_dry_run,
    )

    signal = {
        "symbol": "002050",
        "name": "三花智控",
        "action": args.action,
        "shares": 300 if args.action in ["buy", "sell"] else 0,
        "price": 29.5,
        "rule_id": "mock_rule" if args.action in ["buy", "sell", "review"] else None,
        "reason": "这是通知链路测试，不代表真实交易建议。",
        "triggered_at": datetime.now().astimezone(),
        "raw_metrics": {
            "volume_ratio": 0.8,
        },
    }

    print(
        "PushPlus config: "
        f"dry_run={config.pushplus_dry_run}, "
        f"enable_voice={config.pushplus_enable_voice}, "
        f"normal_channel={config.pushplus_normal_channel}, "
        f"urgent_channel={config.pushplus_urgent_channel}, "
        f"token_configured={bool(config.pushplus_token)}"
    )
    ok = notifier.notify_signal(signal, signal["reason"])
    print(f"通知测试完成: {'success' if ok else 'failed'}")


if __name__ == "__main__":
    main()
