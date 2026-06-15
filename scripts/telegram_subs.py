"""
Shared module for Telegram subscriber management.

- Anyone who sends /start to the bot is auto-subscribed.
- /stop removes them.
- /help shows usage.
- get_all_chat_ids() returns env IDs + dynamic subscribers.
"""
import os
import json
import datetime as dt
from pathlib import Path

import requests

WELCOME = (
    "<b>👋 Добро пожаловать в SR Competitive Monitor!</b>\n\n"
    "Я буду присылать вам:\n"
    "• 📰 Сводки новостей про конкурентов Smart Restaurant в Казахстане (каждый день в 10:00 Алматы)\n"
    "• 🔔 Алерты об изменениях цен/фич на сайтах вендоров\n\n"
    "<b>Команды:</b>\n"
    "/start — подписаться (вы уже сделали ✓)\n"
    "/stop — отписаться\n"
    "/help — эта справка\n\n"
    "Первая сводка придёт в течение суток (после ближайшего автозапуска)."
)

HELP_MSG = (
    "<b>SR Competitive Monitor — справка</b>\n\n"
    "Я слежу за 18+ конкурентами Smart Restaurant в Казахстане:\n"
    "iiko · r_keeper · Poster · Paloma365 · Choice QR · QRPay · Starter · Kaspi Рестораны · "
    "Wolt · Yandex Eats · Glovo · Plazius · MAXMA · ProBonus · ISOFT · и др.\n\n"
    "<b>Что присылаю:</b>\n"
    "• 📰 News digest — упоминания конкурентов в KZ-СМИ (раз в день)\n"
    "• 🔔 Changes — когда вендор меняет цены или функционал на сайте\n\n"
    "<b>Команды:</b>\n"
    "/start — подписаться\n"
    "/stop — отписаться\n"
    "/help — эта справка\n\n"
    "Сайт-дашборд с полным анализом: https://alexsrchoco.github.io/sr-competitive-news/"
)

GOODBYE = "Вы отписались от рассылки. Чтобы снова подписаться — пришлите /start."


def send_message(token, chat_id, text):
    """Send a single Telegram message. Returns True on success."""
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if r.status_code != 200:
            print(f"  Telegram {chat_id}: {r.status_code} {r.text[:150]}", flush=True)
            return False
        return True
    except Exception as e:
        print(f"  Telegram {chat_id} error: {e}", flush=True)
        return False


def process_commands(subs_file):
    """Fetch new updates from Telegram, process /start /stop /help, save subscribers list.

    Returns (added_count, removed_count) tuple for reporting.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return (0, 0)

    state = {"subscribers": {}, "last_update_id": 0}
    if subs_file.exists():
        try:
            state = json.loads(subs_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    next_offset = (state.get("last_update_id", 0) or 0) + 1
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": next_offset, "timeout": 0, "limit": 100},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"  getUpdates HTTP {r.status_code}: {r.text[:200]}", flush=True)
            return (0, 0)
        updates = r.json().get("result", [])
    except Exception as e:
        print(f"  getUpdates failed: {e}", flush=True)
        return (0, 0)

    added = 0
    removed = 0
    welcome_to = []
    for u in updates:
        state["last_update_id"] = max(state["last_update_id"] or 0, u.get("update_id", 0))
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", "")).strip()
        text = (msg.get("text") or "").strip().lower()
        if not chat_id or not text:
            continue

        # /start, /subscribe — с возможным @bot_name суффиксом
        if text.startswith("/start") or text.startswith("/subscribe"):
            if chat_id not in state["subscribers"]:
                state["subscribers"][chat_id] = {
                    "name": chat.get("first_name") or chat.get("title") or "",
                    "username": chat.get("username", ""),
                    "type": chat.get("type", ""),
                    "subscribed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
                added += 1
                welcome_to.append(chat_id)
            else:
                # Already subscribed — send a quick "you're already in" reply
                send_message(token, chat_id, "Вы уже подписаны ✓ Используйте /help для справки.")
        elif text.startswith("/stop") or text.startswith("/unsubscribe"):
            if chat_id in state["subscribers"]:
                state["subscribers"].pop(chat_id, None)
                removed += 1
                send_message(token, chat_id, GOODBYE)
        elif text.startswith("/help"):
            send_message(token, chat_id, HELP_MSG)

    # Welcome new subscribers
    for chat_id in welcome_to:
        send_message(token, chat_id, WELCOME)

    subs_file.parent.mkdir(parents=True, exist_ok=True)
    subs_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Subscribers: +{added} new, -{removed} unsubscribed, total active: {len(state['subscribers'])}", flush=True)
    return (added, removed)


def get_all_chat_ids(subs_file):
    """Return list of unique chat_ids from env + subscribers file."""
    env_ids = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]
    state = {"subscribers": {}}
    if subs_file.exists():
        try:
            state = json.loads(subs_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    sub_ids = list(state.get("subscribers", {}).keys())
    return list(dict.fromkeys(env_ids + sub_ids))


def broadcast(text):
    """Send a message to all chat_ids (env + subscribers)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return 0
    from pathlib import Path
    subs_file = Path(__file__).resolve().parent.parent / "data" / "subscribers.json"
    chat_ids = get_all_chat_ids(subs_file)
    sent = 0
    for chat_id in chat_ids:
        if send_message(token, chat_id, text):
            sent += 1
    return sent
