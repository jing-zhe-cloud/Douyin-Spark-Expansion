"""运行状态与日志。运行结果持久化到 data/runtime.json，日志同时写文件与内存环形缓冲。"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from pathlib import Path

from .config import DATA_DIR

RUNTIME_PATH = DATA_DIR / "runtime.json"
LOG_DIR = DATA_DIR / "logs"

_lock = threading.Lock()
_ring: deque[str] = deque(maxlen=600)
_activity: dict = {"msg": "", "at": ""}


def _default() -> dict:
    return {"session_status": "unknown", "running": False, "last_run": None, "history": []}


def load_runtime() -> dict:
    rt = _default()
    if RUNTIME_PATH.exists():
        try:
            data = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                rt.update(data)
        except Exception:
            pass
    return rt


def _save(rt: dict) -> None:
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        RUNTIME_PATH.write_text(json.dumps(rt, ensure_ascii=False, indent=2), encoding="utf-8")


def set_running(value: bool) -> None:
    rt = load_runtime()
    rt["running"] = bool(value)
    _save(rt)


def record_run(result: dict) -> None:
    rt = load_runtime()
    rt["last_run"] = result
    history = rt.get("history", [])
    history.insert(0, result)
    rt["history"] = history[:30]

    if result.get("logged_out"):
        rt["session_status"] = "expired"
    elif result.get("ok") and not result.get("failed"):
        rt["session_status"] = "ok"
    elif result.get("ok"):
        rt["session_status"] = "partial"
    elif not result.get("failed"):
        rt["session_status"] = "ok"
    else:
        rt["session_status"] = "failed"
    _save(rt)


def record_contacts(data: dict) -> None:
    rt = load_runtime()
    rt["contacts"] = data.get("names", [])
    rt["contacts_at"] = data.get("at")
    rt["contacts_error"] = data.get("error")
    _save(rt)


def record_auto_reply(result: dict) -> None:
    """记录最近一次自动回复检查结果，供网页端展示。"""
    rt = load_runtime()
    rt["last_auto_reply"] = result
    _save(rt)


def load_replied_keys() -> set:
    """已自动回复过的消息指纹集合（name|消息文本），用于去重。"""
    rt = load_runtime()
    replied = rt.get("replied_messages", [])
    return set(replied) if isinstance(replied, list) else set()


def record_replied(key: str) -> None:
    """记录一条已自动回复的消息指纹，避免同一消息重复回复。

    指纹由调用方构造（好友名 + 对方消息序号 + 回复方式 + 回复内容），
    因此好友再次发来新消息（即使文本相同）也会重新回复。
    """
    rt = load_runtime()
    replied = rt.get("replied_messages", [])
    if not isinstance(replied, list):
        replied = []
    if key not in replied:
        replied.append(key)
        rt["replied_messages"] = replied[-500:]
        _save(rt)


def update_runtime(**fields) -> None:
    rt = load_runtime()
    rt.update(fields)
    _save(rt)


def set_activity(msg: str) -> None:
    """更新当前正在执行的实时活动描述（内存态，供前端实时展示）。"""
    _activity["msg"] = msg
    _activity["at"] = time.strftime("%Y-%m-%d %H:%M:%S")


def get_activity() -> dict:
    """返回当前实时活动描述。"""
    return dict(_activity)


class RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _ring.append(self.format(record))
        except Exception:
            pass


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("douyin-spark")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    rh = RingHandler()
    rh.setFormatter(fmt)
    logger.addHandler(rh)
    return logger


def recent_logs(n: int = 300) -> list[str]:
    return list(_ring)[-n:]
