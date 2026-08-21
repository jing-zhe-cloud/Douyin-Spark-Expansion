"""Playwright 自动化：在抖音网页版私信页面给指定好友发送消息。

发送逻辑参考 douyin-cloud-streak（MIT），要点：
- 点击联系人后校验右侧会话确实切换（防止限流时错发给上一个人）；
- 列表点击失败时用搜索框兜底；
- 检测"操作频繁 / 安全验证"等提示，命中即停本轮；
- 发送前清空输入框，发送后校验输入框已清空。
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

from .config import DATA_DIR, load_config
from .runtime import load_replied_keys, record_replied, set_activity

logger = logging.getLogger("douyin-spark")

STATE_PATH = DATA_DIR / "state.json"
SCREENSHOT_PATH = DATA_DIR / "last_error.png"
CHAT_URL = "https://www.douyin.com/chat"

# 无头浏览器启动参数：附加反自动化检测，降低被抖音识别并断开连接的概率
BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--window-size=1366,768",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

RATE_LIMIT_KEYWORDS = [
    "操作频繁",
    "操作太频繁",
    "发送过于频繁",
    "请稍后再试",
    "稍后再试",
    "安全验证",
    "滑动验证",
    "验证码",
    "验证中心",
    "人机验证",
    "网络异常",
    "请勿频繁",
]

LOGIN_TEXTS = ["扫码登录", "验证码登录", "登录后查看", "登录后即可"]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _screenshot(page) -> None:
    try:
        page.screenshot(path=str(SCREENSHOT_PATH), timeout=5000)
        logger.info("已保存页面截图: %s", SCREENSHOT_PATH)
    except Exception:
        pass


def _launch_browser(p):
    """启动无头浏览器（带反自动化检测参数），并更新实时状态。"""
    set_activity("正在启动浏览器")
    return p.chromium.launch(headless=True, args=BROWSER_ARGS)


def _new_context(browser):
    """创建带登录态和真实 UA 的浏览器上下文。"""
    set_activity("正在加载登录态")
    return browser.new_context(
        storage_state=str(STATE_PATH),
        viewport={"width": 1366, "height": 768},
        user_agent=USER_AGENT,
    )


def _goto_chat(page, label: str) -> bool:
    """打开抖音私信页，带重试与实时状态更新。"""
    for attempt in range(3):
        set_activity(f"{label}：正在打开抖音私信页（第 {attempt + 1} 次）")
        try:
            page.goto(CHAT_URL, timeout=90000, wait_until="domcontentloaded")
            set_activity(f"{label}：打开抖音成功")
            return True
        except Exception as e:
            logger.info("%s 第 %s 次打开页面失败: %s", label, attempt + 1, str(e)[:80])
            set_activity(f"{label}：打开页面失败，等待重试")
            time.sleep(5)
    set_activity(f"{label}：打开抖音失败")
    return False


def check_login(page) -> tuple[bool, str]:
    """返回 (是否已登录, 说明)。宁可误报掉线，也不要带着过期登录态硬跑。"""
    url = page.url
    if "login" in url.lower() or "passport" in url.lower():
        return False, f"页面已跳转到登录页（{url}）"

    try:
        qr = page.locator("#animate_qrcode_container")
        if qr.count() and qr.first.is_visible():
            return False, "页面出现扫码登录二维码，登录态已过期"
    except Exception:
        pass

    for text in LOGIN_TEXTS:
        try:
            loc = page.get_by_text(text, exact=False)
            for i in range(min(loc.count(), 3)):
                if loc.nth(i).is_visible():
                    return False, f"页面出现登录提示「{text}」"
        except Exception:
            continue

    cookies = page.context.cookies()
    if not any(c["name"].startswith("sessionid") for c in cookies):
        return False, "未检测到 sessionid Cookie"
    return True, "ok"


def detect_rate_limit(page) -> str | None:
    for kw in RATE_LIMIT_KEYWORDS:
        try:
            loc = page.get_by_text(kw, exact=False)
            for i in range(loc.count()):
                if loc.nth(i).bounding_box():
                    return kw
        except Exception:
            continue
    return None


def _find_contact(page, name: str):
    """优先按全文精确匹配联系人标题，避免误点其他会话里的消息预览。"""
    exact = page.get_by_text(name, exact=True)
    if exact.count():
        return exact.first
    return page.locator(".conversationConversationItemtitle").filter(has_text=name).first


def verify_in_conversation(page, name: str) -> bool:
    """右侧会话顶部标题区域（x>300 且 y<100）出现目标昵称才算切换成功，防止错发。"""
    for exact in (True, False):
        try:
            loc = page.get_by_text(name, exact=exact)
            for i in range(loc.count()):
                try:
                    box = loc.nth(i).bounding_box()
                except Exception:
                    continue
                if box and box.get("x", 0) > 300 and box.get("y", 0) < 100:
                    return True
        except Exception:
            continue
    return False


def search_and_open(page, name: str) -> bool:
    try:
        box = page.get_by_placeholder("搜索", exact=False).first
        if box.count() == 0:
            return False
        box.click()
        box.fill(name)
        time.sleep(4)
        # 优先直接点搜索结果里的「发消息」按钮，最可靠
        btn = page.get_by_text("发消息", exact=False).first
        if btn.count():
            btn.click(force=True)
            time.sleep(4)
            return True
        # 否则点精确匹配的结果卡片，再找「发消息」入口
        candidate = page.get_by_text(name, exact=True).first
        if candidate.count() == 0:
            candidate = page.get_by_text(name, exact=False).first
        if candidate.count() == 0:
            return False
        candidate.click(force=True)
        time.sleep(3)
        btn = page.get_by_text("发消息", exact=False).first
        if btn.count():
            btn.click(force=True)
            time.sleep(3)
        return True
    except Exception as e:
        logger.info("搜索打开 %s 失败: %s", name, e)
        return False


def _type_and_send(page, input_box, msg_text: str) -> bool:
    """把文字输入输入框并按 Enter 发送，返回文字是否成功进入输入框。"""
    try:
        input_box.click()
        time.sleep(0.4)
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        time.sleep(0.3)
        page.keyboard.type(msg_text, delay=100)
        time.sleep(0.8)
        cur = input_box.inner_text() or ""
        if msg_text not in cur:
            logger.warning("文字未进入输入框，当前内容: %r", cur[:30])
            return False
        page.keyboard.press("Enter")
        return True
    except Exception as e:
        logger.info("输入/发送异常: %s", str(e)[:100])
        return False


def _wait_input_cleared(input_box, msg_text: str, wait: float = 8) -> bool:
    """消息发出后输入框应不再包含发送文字，以此确认真正发出。"""
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(1)
        try:
            cur = input_box.inner_text() or ""
            if msg_text not in cur:
                return True
        except Exception:
            pass
    return False


def send_to_contact(page, name: str, msg_text: str, dry_run: bool) -> tuple[bool, str]:
    switched = False
    for attempt in range(5):
        try:
            target = _find_contact(page, name)
            if target.count():
                target.click(force=True, timeout=10000)
                time.sleep(random.uniform(2, 4))
                if verify_in_conversation(page, name):
                    switched = True
                    break
            else:
                # 目标可能因列表懒加载尚未渲染，滚动侧边栏继续找
                try:
                    page.mouse.move(200, 350)
                    page.mouse.wheel(0, 600)
                except Exception:
                    pass
                time.sleep(1.5)
        except Exception as e:
            logger.info("点击联系人 %s 异常: %s", name, str(e)[:100])
        time.sleep(random.uniform(1, 2))

    if not switched and search_and_open(page, name):
        time.sleep(random.uniform(1, 3))
        switched = verify_in_conversation(page, name)

    if not switched:
        return False, "未能切换到该好友会话（名字不在聊天列表，或页面结构变化）"

    if detect_rate_limit(page):
        return False, "检测到「操作频繁 / 安全验证」提示"

    input_box = page.locator('div[contenteditable="true"]').first
    try:
        if input_box.count() == 0 or input_box.bounding_box() is None:
            return False, "找不到聊天输入框"
        input_box.wait_for(state="visible", timeout=8000)
    except Exception:
        return False, "找不到聊天输入框"

    if dry_run:
        return True, "dry-run"

    try:
        if detect_rate_limit(page):
            return False, "发送前检测到验证提示"
        if not _type_and_send(page, input_box, msg_text):
            return False, "文字未能输入到输入框"
        if _wait_input_cleared(input_box, msg_text, wait=8):
            return True, "ok"
        logger.warning("未检测到消息发出，重试一次：%s", name)
        if detect_rate_limit(page):
            return False, "重试时检测到验证提示"
        if not _type_and_send(page, input_box, msg_text):
            return False, "重试时文字未能输入"
        if _wait_input_cleared(input_box, msg_text, wait=8):
            return True, "ok"
        return False, "发送后输入框未清空，消息可能未发出"
    except Exception as e:
        logger.info("向 %s 发送异常: %s", name, e)
        return False, f"发送异常: {e}"


def fetch_chat_contacts() -> dict:
    """从抖音私信页左侧聊天列表读取联系人（含火花天数），供网页端勾选。"""
    result = {"at": _now(), "names": [], "error": None}
    if not STATE_PATH.exists():
        result["error"] = "尚未上传登录态 state.json"
        return result

    browser = None
    try:
        p = sync_playwright().start()
        try:
            browser = _launch_browser(p)
            context = _new_context(browser)
            page = context.new_page()

            if not _goto_chat(page, "获取联系人"):
                result["error"] = "无法打开抖音私信页面"
                return result

            page.wait_for_timeout(10000)
            logged, why = check_login(page)
            if not logged:
                result["error"] = why
                return result

            extract_js = """
                () => {
                    const out = [];
                    const seen = new Set();
                    document.querySelectorAll('.conversationConversationItemtitle').forEach(t => {
                        const name = (t.textContent || '').trim();
                        if (!name || seen.has(name)) return;
                        seen.add(name);
                        const wrap = t.parentElement;
                        const s = wrap ? wrap.querySelector('.commonStreaknormalText') : null;
                        out.push({ name: name, streak: s ? (s.textContent || '').trim() : '' });
                    });
                    return out;
                }
            """

            collected: list[dict] = []
            set_activity("正在读取聊天列表")
            for attempt in range(3):
                try:
                    page.wait_for_selector(".conversationConversationItemtitle", timeout=45000)
                except Exception:
                    logger.info("第 %s 次等待联系人列表超时", attempt + 1)

                stable = 0
                for _ in range(20):
                    data = page.evaluate(extract_js) or []
                    new_items = [x for x in data if x not in collected]
                    if new_items:
                        collected.extend(new_items)
                        stable = 0
                    else:
                        stable += 1
                        if stable >= 2:
                            break
                    try:
                        page.mouse.move(200, 350)
                        page.mouse.wheel(0, 800)
                    except Exception:
                        pass
                    page.wait_for_timeout(1200)

                if collected:
                    break
                try:
                    page.reload(wait_until="domcontentloaded", timeout=90000)
                    page.wait_for_timeout(12000)
                except Exception:
                    pass

            result["names"] = collected
            logger.info("已读取聊天列表联系人 %s 个", len(result["names"]))
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            p.stop()
    except Exception as e:
        logger.error("获取联系人异常: %s", e)
        result["error"] = f"获取联系人异常: {e}"
    return result


def run_send(dry_run: bool = False, only_names: list[str] | None = None) -> dict:
    cfg = load_config()
    friends = cfg.get("friends") or []
    if only_names is not None:
        friends = [f for f in friends if f in only_names]
    messages = cfg.get("messages") or ["🔥"]
    max_n = int(cfg.get("max_friends_per_run", 20) or 20)
    gap_min = max(1, int(cfg.get("send_gap_min", 6) or 6))
    gap_max = max(gap_min, int(cfg.get("send_gap_max", 12) or 12))

    result = {
        "at": _now(),
        "dry_run": bool(dry_run),
        "ok": [],
        "failed": [],
        "logged_out": False,
        "rate_limited": False,
    }

    if not STATE_PATH.exists():
        result["failed"].append({"name": "_system", "reason": "尚未上传登录态 state.json"})
        return result

    targets = friends[:max_n] if max_n > 0 else friends
    browser = None
    try:
        p = sync_playwright().start()
        try:
            browser = _launch_browser(p)
            context = _new_context(browser)
            page = context.new_page()

            if not _goto_chat(page, "续火花发送"):
                result["failed"].append({"name": "_system", "reason": "无法打开抖音私信页面"})
                return result

            time.sleep(8)
            logged, why = check_login(page)
            if not logged:
                result["logged_out"] = True
                result["failed"].append({"name": "_system", "reason": why})
                _screenshot(page)
                return result

            if not targets:
                logger.info("未配置任何好友，跳过发送")
                return result

            logger.info("待发送好友 %s 人，dry_run=%s", len(targets), dry_run)
            for name in targets:
                set_activity(f"续火花：正在发送给 {name}")
                msg = random.choice(messages)
                ok, why = send_to_contact(page, name, msg, dry_run)
                if ok:
                    result["ok"].append(name)
                    logger.info("已发送给 %s：%s", name, msg if not dry_run else "(干跑，未真实发送)")
                else:
                    result["failed"].append({"name": name, "reason": why})
                    logger.warning("发送给 %s 失败：%s", name, why)
                    if detect_rate_limit(page):
                        result["rate_limited"] = True
                        logger.warning("疑似触发限流，停止本轮")
                        break
                time.sleep(random.uniform(gap_min, gap_max))
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            p.stop()
    except Exception as e:
        logger.error("运行异常: %s", e)
        result["failed"].append({"name": "_system", "reason": f"运行异常: {e}"})
    return result


def _last_incoming_text(page) -> str:
    """读取会话中最新一条「对方发来的」消息文本。

    抖音消息气泡 .messageMessageBoxcontentBox 上带 isFromMe 类表示自己发的，
    不带则表示对方发的；DOM 顺序为从新到旧，取第一个不带 isFromMe 的即可。
    """
    try:
        return page.evaluate(
            """
            () => {
              const boxes = document.querySelectorAll('.messageMessageBoxcontentBox');
              for (const b of boxes) {
                if (!((b.className || '').includes('isFromMe'))) {
                  const t = (b.textContent || '').trim();
                  if (t) return t;
                }
              }
              return '';
            }
            """
        )
    except Exception as e:
        logger.info("读取对方消息异常: %s", str(e)[:100])
        return ""


def _incoming_count(page) -> int:
    """统计对方发来的消息数量（不含 isFromMe 的 contentBox），用于区分新旧消息。"""
    try:
        return page.evaluate(
            """
            () => {
              let n = 0;
              document.querySelectorAll('.messageMessageBoxcontentBox').forEach(b => {
                if (!((b.className || '').includes('isFromMe'))) n++;
              });
              return n;
            }
            """
        )
    except Exception:
        return 0


def _in_time_window(start: str, end: str) -> bool:
    """判断当前时间是否落在 [start, end] 区间内（支持跨天，如 22:00-08:00）。"""
    now = datetime.now()
    cur = now.hour * 60 + now.minute

    def _to_min(s: str) -> int:
        hh, mm = str(s).split(":")
        return int(hh) * 60 + int(mm)

    s = _to_min(start)
    e = _to_min(end)
    if s == e:
        return True
    if s < e:
        return s <= cur < e
    return cur >= s or cur < e


def check_and_reply(dry_run: bool = False) -> dict:
    """定时轮询：检查自动回复专用好友名单的新私信，按固定回复 / 关键词规则自动回复。

    去重依据「好友名 + 对方消息文本」的指纹，避免同一条消息被重复回复。
    """
    cfg = load_config()
    friends = cfg.get("auto_reply_friends") or []
    fixed_enabled = bool(cfg.get("auto_reply_fixed_enabled"))
    fixed_text = str(cfg.get("auto_reply_fixed_text") or "").strip()
    fixed_start = str(cfg.get("auto_reply_fixed_start") or "09:00")
    fixed_end = str(cfg.get("auto_reply_fixed_end") or "18:00")
    keyword_enabled = bool(cfg.get("auto_reply_keyword_enabled"))
    rules = cfg.get("auto_reply_rules") or []
    gap_min = max(1, int(cfg.get("send_gap_min", 6) or 6))
    gap_max = max(gap_min, int(cfg.get("send_gap_max", 12) or 12))

    result = {
        "at": _now(),
        "enabled": bool(cfg.get("auto_reply_enabled")),
        "dry_run": bool(dry_run),
        "checked": 0,
        "replied": [],
        "skipped": 0,
        "deduped": 0,
        "logged_out": False,
        "rate_limited": False,
    }
    if not result["enabled"]:
        return result
    if not friends:
        logger.info("自动回复：未配置好友名单，跳过")
        return result
    if not (fixed_enabled and fixed_text) and not (keyword_enabled and rules):
        logger.info("自动回复：未启用固定回复或关键词规则，跳过")
        return result
    if not STATE_PATH.exists():
        result["logged_out"] = True
        return result

    replied_keys = load_replied_keys()
    browser = None
    try:
        p = sync_playwright().start()
        try:
            browser = _launch_browser(p)
            context = _new_context(browser)
            page = context.new_page()

            if not _goto_chat(page, "自动回复"):
                return result

            time.sleep(8)
            logged, why = check_login(page)
            if not logged:
                result["logged_out"] = True
                logger.warning("自动回复：登录态检查失败 - %s", why)
                return result

            for name in friends:
                result["checked"] += 1
                set_activity(f"自动回复：正在检查 {name}")
                if detect_rate_limit(page):
                    result["rate_limited"] = True
                    logger.warning("自动回复：检测到限流，停止本轮")
                    break

                switched = False
                try:
                    target = _find_contact(page, name)
                    if target.count():
                        target.click(force=True, timeout=10000)
                        time.sleep(random.uniform(2, 4))
                        switched = verify_in_conversation(page, name)
                except Exception as e:
                    logger.info("自动回复点击 %s 异常: %s", name, str(e)[:100])
                if not switched:
                    result["skipped"] += 1
                    continue

                text = _last_incoming_text(page)
                if not text:
                    continue

                reply_text = None
                reply_type = None
                if keyword_enabled:
                    for rule in rules:
                        kw = str(rule.get("keyword", "")).strip()
                        if kw and kw in text:
                            reply_text = str(rule.get("reply", "")).strip()
                            reply_type = "keyword"
                            break
                if reply_text is None and fixed_enabled and fixed_text and _in_time_window(fixed_start, fixed_end):
                    reply_text = fixed_text
                    reply_type = "fixed"
                if reply_text is None:
                    continue

                incoming = _incoming_count(page)
                key = f"{name}|{incoming}|{reply_type}|{reply_text}"
                if key in replied_keys:
                    result["deduped"] += 1
                    continue

                ok, why = send_to_contact(page, name, reply_text, dry_run=dry_run)
                if ok:
                    if not dry_run:
                        record_replied(key)
                    result["replied"].append(
                        {"name": name, "type": reply_type, "text": reply_text}
                    )
                    logger.info(
                        "自动回复%s %s（%s）-> %s",
                        "（干跑）" if dry_run else "",
                        name,
                        reply_type,
                        reply_text,
                    )
                else:
                    logger.warning("自动回复 %s 失败：%s", name, why)
                time.sleep(random.uniform(gap_min, gap_max))
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            p.stop()
    except Exception as e:
        logger.error("自动回复异常: %s", e)
    return result
