"""
Shared module for Telegram bot interactions.

- /start auto-subscribes user
- /stop unsubscribes
- /help shows usage
- Any other message → treated as query → searches data → sends fact-summary
- get_all_chat_ids() returns env IDs + dynamic subscribers
"""
import os
import re
import json
import datetime as dt
from pathlib import Path

import requests

WELCOME = (
    "<b>👋 Добро пожаловать в SR Competitive Monitor!</b>\n\n"
    "Я буду присылать вам:\n"
    "• 📰 Сводки новостей про конкурентов Smart Restaurant в Казахстане (каждый день в 10:00 Алматы)\n"
    "• 🔔 Алерты об изменениях цен/фич на сайтах вендоров\n"
    "• 📱 Свежие посты из Telegram-каналов конкурентов\n\n"
    "<b>Команды:</b>\n"
    "/start — подписаться (вы уже сделали ✓)\n"
    "/stop — отписаться\n"
    "/help — справка и примеры вопросов\n\n"
    "<b>🔍 Задайте мне вопрос!</b>\n"
    "Напишите что угодно — я найду ответ в собранных данных. Примеры:\n"
    "• «Halyk Bank подключение»\n"
    "• «iiko цены»\n"
    "• «Что нового у Wolt»\n"
    "• «QRPay тарифы»\n\n"
    "Ответ приходит за 5–15 минут (бот проверяет запросы периодически)."
)

HELP_MSG = (
    "<b>SR Competitive Monitor — справка</b>\n\n"
    "Я слежу за 19+ конкурентами Smart Restaurant в Казахстане:\n"
    "iiko · r_keeper · Poster · Paloma365 · Choice QR · QRPay · Starter · Kaspi · "
    "<b>Halyk Restaurants</b> · Wolt · Yandex Eats · Glovo · Plazius · MAXMA · ProBonus · ISOFT · Jowi · Quick Resto · и др.\n\n"
    "<b>Команды:</b>\n"
    "/start — подписаться\n"
    "/stop — отписаться\n"
    "/help — эта справка\n\n"
    "<b>🔍 Поиск по запросу</b> (просто напишите вопрос):\n"
    "• «Halyk Bank подключение» — как работает onboarding\n"
    "• «iiko Cloud цена» — тарифы iiko\n"
    "• «Choice QR функции» — что предлагает Choice\n"
    "• «новости Wolt» — последние упоминания\n"
    "• «изменения Kaspi» — что недавно поменялось\n\n"
    "Ответ приходит за 5–15 минут (workflow на GitHub Actions).\n\n"
    "<b>Сайт с полным анализом:</b>\n"
    "https://alexsrchoco.github.io/sr-competitive-news/"
)

GOODBYE = "Вы отписались от рассылки. Чтобы снова подписаться — пришлите /start."

NO_RESULTS = (
    "🤷 По вашему запросу ничего не нашёл.\n\n"
    "Попробуйте конкретнее — например:\n"
    "• «Halyk Bank подключение»\n"
    "• «iiko цены»\n"
    "• «QRPay тарифы»\n"
    "• «Wolt комиссия»\n\n"
    "Список отслеживаемых конкурентов: /help"
)

# Stop-words for Russian/English query parsing
STOP_WORDS = {
    "как", "что", "у", "и", "в", "на", "с", "по", "для", "про", "о", "при", "ли",
    "же", "это", "мне", "тебе", "нам", "нас", "их", "его", "её", "ее", "я", "ты",
    "он", "она", "мы", "вы", "они", "какие", "какой", "какая", "где", "когда",
    "почему", "зачем", "сколько", "the", "of", "in", "to", "is", "and", "or",
    "новости", "новость",
}


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


# ============== QUERY SEARCH ==============

def extract_keywords(text):
    """Extract significant words from query."""
    cleaned = re.sub(r"[^\w\sа-яёА-ЯЁ]", " ", text.lower())
    words = [w.strip() for w in cleaned.split() if len(w.strip()) >= 3]
    return [w for w in words if w not in STOP_WORDS]


def load_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def search_data(keywords, data_dir):
    """Search news.json, vendors.json, telegram_posts.json for keywords."""
    findings = {"vendor_info": None, "news": [], "telegram": []}
    if not keywords:
        return findings

    # ----- 1. Find primary vendor (longest keyword match wins) -----
    vendors_data = load_json(data_dir / "vendors.json")
    best_match = None
    best_score = 0
    for v in vendors_data.get("vendors", []):
        name_low = v.get("name", "").lower()
        # Score = number of keyword chars in vendor name
        score = sum(len(kw) for kw in keywords if kw in name_low)
        if score > best_score:
            best_score = score
            best_match = v
    if best_match and best_score >= 3:  # require minimal match
        findings["vendor_info"] = best_match
    primary_vendor_low = (best_match or {}).get("name", "").lower()

    # ----- 2. News matching -----
    news_data = load_json(data_dir / "news.json")
    for comp, items in (news_data.get("by_competitor") or {}).items():
        comp_low = comp.lower()
        is_primary = primary_vendor_low and primary_vendor_low in comp_low
        for item in items:
            text = (comp + " " + item.get("title", "") + " " + item.get("source", "")).lower()
            if is_primary or any(kw in text for kw in keywords):
                findings["news"].append({"competitor": comp, **item})
                if len(findings["news"]) >= 8:
                    break
        if len(findings["news"]) >= 8:
            break

    # ----- 3. Telegram matching -----
    tg_data = load_json(data_dir / "telegram_posts.json")
    for ch_name, posts in (tg_data.get("by_channel") or {}).items():
        for p in posts:
            text = (ch_name + " " + p.get("text", "") + " " + str(p.get("vendor", ""))).lower()
            if any(kw in text for kw in keywords):
                findings["telegram"].append({"channel_name": ch_name, **p})
                if len(findings["telegram"]) >= 6:
                    break
        if len(findings["telegram"]) >= 6:
            break

    return findings


def format_query_answer(query, findings):
    """Format findings into HTML Telegram message."""
    if not findings["vendor_info"] and not findings["news"] and not findings["telegram"]:
        return NO_RESULTS

    msg = f"🔍 <b>SR Monitor — по вашему запросу:</b>\n«{query[:200]}»\n\n"

    # --- Vendor info block ---
    if findings["vendor_info"]:
        v = findings["vendor_info"]
        ex = v.get("extracted") or {}
        msg += f"🌐 <b>{v.get('name','?')}</b>"
        meta = " · ".join([x for x in [v.get("type"), v.get("country")] if x])
        if meta:
            msg += f"  <i>({meta})</i>"
        msg += "\n\n"

        if ex.get("tagline"):
            msg += f"<i>«{ex['tagline'][:160]}»</i>\n\n"

        tiers = ex.get("pricing_tiers") or []
        if tiers:
            msg += "🏷 <b>Найденные цены:</b>\n"
            for t in tiers[:5]:
                price = t.get("price_text", "?")
                ctx = (t.get("context") or "")[:80]
                msg += f"  • <b>{price}</b>"
                if ctx:
                    msg += f" — {ctx}…"
                msg += "\n"
            msg += "\n"

        features = ex.get("features") or []
        if features:
            msg += "✨ <b>Функции:</b> " + ", ".join(features[:10]) + "\n\n"

        integrations = ex.get("integrations") or []
        if integrations:
            msg += "🔌 <b>Интеграции:</b> " + ", ".join(integrations[:8]) + "\n\n"

        clients = ex.get("notable_clients") or []
        if clients:
            msg += "👥 <b>Клиенты:</b> " + ", ".join(clients[:5]) + "\n\n"

        urls = v.get("urls") or []
        if urls:
            msg += f"📍 <a href=\"{urls[0]}\">Открыть сайт</a>\n\n"

    # --- News block ---
    if findings["news"]:
        msg += f"📰 <b>Новости ({len(findings['news'])}):</b>\n"
        for n in findings["news"][:5]:
            title = (n.get("title") or "")[:130]
            source = n.get("source", "")
            url = n.get("url", "")
            published = n.get("published", "")[:10]
            msg += f"• <a href=\"{url}\">{title}</a>\n"
            if source or published:
                msg += f"  <i>{source} · {published}</i>\n"
        msg += "\n"

    # --- Telegram block ---
    if findings["telegram"]:
        msg += f"📱 <b>Telegram-каналы ({len(findings['telegram'])}):</b>\n"
        for p in findings["telegram"][:4]:
            snippet = (p.get("text") or "")[:200].replace("\n", " ").strip()
            ch_name = p.get("channel_name") or p.get("channel", "")
            url = p.get("url", "")
            date_iso = p.get("published", "")[:10]
            msg += f"• <i>@{ch_name}</i> · {date_iso}:\n  {snippet}…\n"
            if url:
                msg += f"  <a href=\"{url}\">Открыть</a>\n"
        msg += "\n"

    msg += "<i>ℹ️ Данные на момент последнего автоматического сбора. Полная картина: https://alexsrchoco.github.io/sr-competitive-news/</i>"

    if len(msg) > 4000:
        msg = msg[:3950] + "\n\n…(обрезано)"
    return msg


def handle_query(token, chat_id, text, data_dir):
    """User sent a non-command message → search & respond."""
    keywords = extract_keywords(text)
    if not keywords:
        send_message(
            token, chat_id,
            "Не разобрал вопрос. Попробуйте короче и конкретнее — например: «Halyk Bank подключение» или «iiko цены»."
        )
        return
    findings = search_data(keywords, data_dir)
    answer = format_query_answer(text, findings)
    send_message(token, chat_id, answer)


# ============== COMMAND PROCESSING ==============

def process_commands(subs_file):
    """Fetch new updates from Telegram, process commands & queries, save state.

    Returns (added_count, removed_count, queries_count) for reporting.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return (0, 0, 0)

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
            return (0, 0, 0)
        updates = r.json().get("result", [])
    except Exception as e:
        print(f"  getUpdates failed: {e}", flush=True)
        return (0, 0, 0)

    data_dir = subs_file.parent  # data/

    added = 0
    removed = 0
    queries = 0
    welcome_to = []
    queries_to_handle = []  # (chat_id, text) — process after state save

    for u in updates:
        state["last_update_id"] = max(state["last_update_id"] or 0, u.get("update_id", 0))
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", "")).strip()
        text = (msg.get("text") or "").strip()
        text_low = text.lower()
        if not chat_id or not text:
            continue

        if text_low.startswith("/start") or text_low.startswith("/subscribe"):
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
                send_message(token, chat_id, "Вы уже подписаны ✓ Задайте мне любой вопрос — например «Halyk Bank подключение». /help — справка.")
        elif text_low.startswith("/stop") or text_low.startswith("/unsubscribe"):
            if chat_id in state["subscribers"]:
                state["subscribers"].pop(chat_id, None)
                removed += 1
                send_message(token, chat_id, GOODBYE)
        elif text_low.startswith("/help"):
            send_message(token, chat_id, HELP_MSG)
        elif text_low.startswith("/"):
            # Unknown command
            send_message(token, chat_id, "Неизвестная команда. /help — справка.")
        else:
            # Treat as query
            queries_to_handle.append((chat_id, text))
            queries += 1

    # Send welcomes
    for chat_id in welcome_to:
        send_message(token, chat_id, WELCOME)

    # Handle queries (may take time per query — last to do)
    for chat_id, query_text in queries_to_handle:
        try:
            handle_query(token, chat_id, query_text, data_dir)
        except Exception as e:
            print(f"  query handler failed: {e}", flush=True)
            send_message(token, chat_id, "Произошла ошибка при поиске. Попробуйте позже или напишите /help.")

    subs_file.parent.mkdir(parents=True, exist_ok=True)
    subs_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Subs: +{added}/-{removed}, queries: {queries}, total active: {len(state['subscribers'])}", flush=True)
    return (added, removed, queries)


def get_all_chat_ids(subs_file):
    """Return unique chat_ids from env + subscribers file."""
    env_ids = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]
    state = {"subscribers": {}}
    if subs_file.exists():
        try:
            state = json.loads(subs_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    sub_ids = list(state.get("subscribers", {}).keys())
    return list(dict.fromkeys(env_ids + sub_ids))
