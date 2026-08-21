"""配置读写。配置保存在 data/config.json，由网页端编辑。"""

from __future__ import annotations

import json
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "schedule_time": "21:00",   # 每天发送时间 HH:MM（服务器时区 Asia/Shanghai）
    "jitter_minutes": 30,       # 时间抖动窗口：实际在 [schedule_time, schedule_time+30min] 内随机开始
    "send_gap_min": 6,          # 相邻两个好友之间的最小间隔（秒）
    "send_gap_max": 12,         # 相邻两个好友之间的最大间隔（秒）
    "max_friends_per_run": 20,  # 每次最多发送的好友数（0 表示不限制）
    "friends": [],              # 好友列表：聊天列表里显示的备注 / 昵称 / 抖音号
    "messages": ["🔥 续火花", "晚安，明天见", "今天也要开心哦"],
    "auto_reply_enabled": False,           # 自动回复总开关
    "auto_reply_interval_minutes": 5,      # 轮询间隔（分钟）
    "auto_reply_friends": [],              # 自动回复专用好友名单（与 friends 隔离）
    "auto_reply_fixed_enabled": False,     # 固定回复开关
    "auto_reply_fixed_text": "",           # 固定回复文案
    "auto_reply_fixed_start": "09:00",     # 固定回复生效开始时间（HH:MM）
    "auto_reply_fixed_end": "18:00",       # 固定回复生效结束时间（HH:MM）
    "auto_reply_keyword_enabled": False,   # 关键词规则开关
    "auto_reply_rules": [],                # 关键词规则：[{"keyword": "在吗", "reply": "在的"}]
}

_lock = threading.Lock()


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict | None) -> dict:
    merged = dict(DEFAULT_CONFIG)
    if cfg:
        merged.update(cfg)

    merged["friends"] = [str(x).strip() for x in merged.get("friends", []) if str(x).strip()]
    merged["messages"] = [str(x) for x in merged.get("messages", []) if str(x).strip()]
    if not merged["messages"]:
        merged["messages"] = ["🔥"]

    # 自动回复配置
    merged["auto_reply_enabled"] = bool(merged.get("auto_reply_enabled", False))
    try:
        merged["auto_reply_interval_minutes"] = max(1, min(1440, int(merged.get("auto_reply_interval_minutes", 5) or 5)))
    except (TypeError, ValueError):
        raise ValueError("auto_reply_interval_minutes 必须是整数")

    merged["auto_reply_friends"] = [str(x).strip() for x in merged.get("auto_reply_friends", []) if str(x).strip()]
    merged["auto_reply_fixed_enabled"] = bool(merged.get("auto_reply_fixed_enabled", False))
    merged["auto_reply_fixed_text"] = str(merged.get("auto_reply_fixed_text", "") or "").strip()
    for key in ("auto_reply_fixed_start", "auto_reply_fixed_end"):
        val = str(merged.get(key, "09:00"))
        try:
            hh, mm = val.split(":")
            if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                raise ValueError
            merged[key] = f"{int(hh):02d}:{int(mm):02d}"
        except Exception:
            raise ValueError(f"{key} 必须是 HH:MM 格式")
    merged["auto_reply_keyword_enabled"] = bool(merged.get("auto_reply_keyword_enabled", False))

    rules = merged.get("auto_reply_rules") or []
    normalized = []
    if isinstance(rules, list):
        for r in rules:
            if not isinstance(r, dict):
                continue
            kw = str(r.get("keyword", "")).strip()
            reply = str(r.get("reply", "")).strip()
            if kw and reply:
                normalized.append({"keyword": kw, "reply": reply})
    merged["auto_reply_rules"] = normalized

    schedule = str(merged.get("schedule_time", "21:00"))
    try:
        hh, mm = schedule.split(":")
        if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            raise ValueError
        merged["schedule_time"] = f"{int(hh):02d}:{int(mm):02d}"
    except Exception:
        raise ValueError("schedule_time 必须是 HH:MM 格式")

    for key in ("jitter_minutes", "send_gap_min", "send_gap_max", "max_friends_per_run"):
        try:
            merged[key] = max(0, int(merged.get(key, DEFAULT_CONFIG[key])))
        except (TypeError, ValueError):
            raise ValueError(f"{key} 必须是整数")
    if merged["send_gap_max"] < merged["send_gap_min"]:
        merged["send_gap_max"] = merged["send_gap_min"]

    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged
