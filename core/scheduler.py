"""每天定时触发发送任务。"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import load_config

logger = logging.getLogger("douyin-spark")
TZ = "Asia/Shanghai"

_scheduler: BackgroundScheduler | None = None
_run_func: Callable | None = None
_auto_reply_func: Callable | None = None


def _daily_job() -> None:
    cfg = load_config()
    jitter = max(0, int(cfg.get("jitter_minutes", 30) or 30))
    if jitter:
        delay = random.uniform(0, jitter * 60)
        logger.info("随机延迟 %.0f 秒后开始发送（抖动窗口 %s 分钟）", delay, jitter)
        time.sleep(delay)
    if _run_func:
        _run_func()


def configure(run_func: Callable, auto_reply_func: Callable | None = None) -> None:
    global _scheduler, _run_func, _auto_reply_func
    _run_func = run_func
    if auto_reply_func is not None:
        _auto_reply_func = auto_reply_func
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=TZ)
        _scheduler.start()
    apply_schedule()
    if auto_reply_func is not None:
        apply_auto_reply_schedule()


def apply_schedule() -> None:
    if _scheduler is None:
        return
    cfg = load_config()
    hh, mm = cfg.get("schedule_time", "21:00").split(":")
    _scheduler.add_job(
        _daily_job,
        CronTrigger(hour=int(hh), minute=int(mm), timezone=TZ),
        id="daily_send",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=3600,
    )
    logger.info("定时任务已更新：每天 %s:%s (%s)", hh, mm, TZ)


def next_run_time() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job("daily_send")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def apply_auto_reply_schedule() -> None:
    if _scheduler is None or _auto_reply_func is None:
        return
    cfg = load_config()
    if not cfg.get("auto_reply_enabled"):
        if _scheduler.get_job("auto_reply"):
            _scheduler.remove_job("auto_reply")
        return
    minutes = max(1, min(1440, int(cfg.get("auto_reply_interval_minutes", 5) or 5)))
    # 启动后约 30 秒先跑一次，之后按固定间隔轮询
    _scheduler.add_job(
        _auto_reply_func,
        IntervalTrigger(minutes=minutes, timezone=TZ),
        id="auto_reply",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=60,
        next_run_time=datetime.now() + timedelta(seconds=30),
    )
    logger.info("自动回复轮询已更新：每 %s 分钟", minutes)


def next_auto_reply_time() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job("auto_reply")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def schedule_retry(run_func: Callable, delay_minutes: int = 45) -> None:
    if _scheduler is None:
        return
    if _scheduler.get_job("retry_send"):
        return
    run_at = datetime.now() + timedelta(minutes=delay_minutes)
    _scheduler.add_job(
        run_func,
        DateTrigger(run_date=run_at, timezone=TZ),
        id="retry_send",
        replace_existing=True,
    )
    logger.info("已安排 %s 分钟后自动补发本次失败的好友", delay_minutes)


def cancel_retry() -> None:
    if _scheduler and _scheduler.get_job("retry_send"):
        _scheduler.remove_job("retry_send")
        logger.info("已取消待执行的补发任务")


def shutdown() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
