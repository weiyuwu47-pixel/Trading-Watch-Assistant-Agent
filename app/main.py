from __future__ import annotations

import argparse
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler

from app.config import load_app_config
from app.scheduler import run_once


def _job() -> None:
    config = load_app_config()
    print(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] 开始执行盯盘任务")
    result = run_once(config)
    print(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] 任务结束: {result.status} {result.message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="personal-stock-watch-agent")
    parser.add_argument("--interval-minutes", type=int, default=None, help="测试用：每隔 N 分钟运行一次")
    args = parser.parse_args()

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    if args.interval_minutes:
        scheduler.add_job(_job, "interval", minutes=args.interval_minutes, next_run_time=datetime.now())
        print(f"已启动间隔任务：每 {args.interval_minutes} 分钟运行一次")
    else:
        for hour, minute in [(11, 35), (14, 45), (15, 10)]:
            scheduler.add_job(_job, "cron", hour=hour, minute=minute)
        print("已启动定时任务：每天 11:35、14:45、15:10 运行")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("盯盘任务已停止")


if __name__ == "__main__":
    main()
