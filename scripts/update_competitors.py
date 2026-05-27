#!/usr/bin/env python3
"""
SR Competitive Monitor — daily news fetcher.

Fetches Google News RSS for each competitor, dedupes,
saves to ../data/news.json, sends digest to Telegram.

Optional AI summarization via Anthropic API.
"""
import os
import sys
import json
import time
import urllib.parse
import datetime as dt
from pathlib import Path

import feedparser
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "news.json"

# ----------------------------- COMPETITORS -----------------------------
# Tweak this list to track different vendors. Each entry: name + Russian/English search query
COMPETITORS = [
    {"name": "iiko",        "query": "iiko Казахстан ресторан"},
    {"name": "Choice QR",   "query": '"Choice QR" OR "ChoiceQR" ресторан'},
    {"name": "QRPay",       "query": "QRPay Казахстан ресторан"},
    {"name": "Starter",     "query": '"Starter" "starterapp" ресторан Казахстан'},
    {"name": "r_keeper",    "query": '"r_keeper" OR "r-keeper" Казахстан'},
    {"name": "Poster POS",  "query": '"Poster POS" Казахстан'},
    {"name": "Paloma365",   "query": "Paloma365 Казахстан"},
    {"name": "Quick Resto", "query": '"Quick Resto" Казахстан'},
    {"name": "Jowi",        "query": "Jowi Казахстан ресторан"},
    {"name": "Kaspi Рестораны", "query": '"Kaspi Рестораны" OR "Kaspi.kz рестораны"'},
    {"name": "Wolt",        "query": "Wolt Казахстан ресторан комиссия"},
    {"name": "Yandex Eats", "query": "Яндекс Еда Казахстан ресторан"},
    {"name": "Glovo",       "query": "Glovo Казахстан ресторан"},
    {"name": "Plazius",     "query": "Plazius лояльность ресторан"},
    {"name": "MAXMA",       "query": "MAXMA лояльность ресторан"},
    {"name": "ProBonus",    "query": "ProBonus Carbis r_keeper лояльность"},
    {"name": "ISOFT KZ",    "query": '"ISOFT" Казахстан POS-системы'},
    # Smart Restaurant — отслеживаем сами себя
    {"name": "Smart Restaurant by Choco", "query": '"Smart Restaurant" Choco Казахстан'},
]

# How many days back to look
LOOKBACK_DAYS = 7

# Max items per competitor in JSON
MAX_PER_COMPETITOR = 5

# ----------------------------- FETCH -----------------------------
def google_news_rss_url(query, lang="ru", country="KZ"):
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl={lang}-{country}&gl={country}&ceid={country}:{lang}"

def fetch_news_for_competitor(comp):
    url = google_news_rss_url(comp["query"])
    print(f"  → fetching: {comp['name']}", flush=True)
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        print(f"    error: {e}", flush=True)
        return []

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=LOOKBACK_DAYS)
    items = []
    for entry in feed.entries[:MAX_PER_COMPETITOR * 3]:  # over-fetch a bit, then filter
        pub = entry.get("published_parsed") or entry.get("updated_parsed")
        if not pub:
            continue
        pub_dt = dt.datetime(*pub[:6], tzinfo=dt.timezone.utc)
        if pub_dt < cutoff:
            continue
        items.append({
            "title": entry.title,
            "url": entry.link,
            "source": entry.get("source", {}).get("title", "") or _domain(entry.link),
            "published": pub_dt.isoformat(),
        })
        if len(items) >= MAX_PER_COMPETITOR:
            break
    return items

def _domain(url):
    try:
        return urllib.parse.urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""

# ----------------------------- AI SUMMARIZATION (optional) -----------------------------
def summarize_with_claude(news_by_competitor):
    """Use Anthropic API to write 1-line 'why this matters for SR' summary per item.
    Returns the same dict but enriched with .summary field on each item."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return news_by_competitor

    # Build a compact prompt with ALL items at once to save API calls
    items_flat = []
    for comp_name, items in news_by_competitor.items():
        for item in items:
            items_flat.append({"competitor": comp_name, "title": item["title"], "source": item.get("source","")})

    if not items_flat:
        return news_by_competitor

    prompt = (
        "Ты — аналитик Smart Restaurant by Choco (KZ). Для каждой новости ниже напиши ОДНУ строку (max 100 знаков) "
        "на русском: «что это значит для SR» — фокус на угрозах/возможностях. "
        "Если новость не релевантна — пиши «Не критично».\n\n"
        "Новости:\n"
    )
    for i, it in enumerate(items_flat, 1):
        prompt += f"{i}. [{it['competitor']}] {it['title']} ({it['source']})\n"
    prompt += "\nОтветь строго в формате JSON-массива строк, по одной на новость, в том же порядке."

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"]
        # Try to parse JSON array
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            summaries = json.loads(text[start:end+1])
            idx = 0
            for comp_name, items in news_by_competitor.items():
                for item in items:
                    if idx < len(summaries):
                        item["summary"] = summaries[idx]
                    idx += 1
    except Exception as e:
        print(f"AI summarization failed: {e}", flush=True)
    return news_by_competitor

# ----------------------------- TELEGRAM -----------------------------
def send_telegram_digest(news_by_competitor):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = os.environ.get("TELEGRAM_CHAT_IDS", "").strip()
    if not token or not chat_ids:
        print("Telegram secrets missing — skipping digest send.", flush=True)
        return

    total = sum(len(items) for items in news_by_competitor.values())
    if total == 0:
        msg = (
            f"<b>📰 SR Competitive Monitor — {dt.date.today().isoformat()}</b>\n\n"
            f"За последние {LOOKBACK_DAYS} дней о наших конкурентах в KZ-сегменте — тихо. "
            f"Ничего нового не нашли."
        )
    else:
        lines = [f"<b>📰 SR Competitive Monitor — {dt.date.today().isoformat()}</b>"]
        lines.append(f"Найдено <b>{total}</b> упоминаний за последние {LOOKBACK_DAYS} дней:\n")
        for comp_name, items in news_by_competitor.items():
            if not items:
                continue
            lines.append(f"<b>🔸 {comp_name}</b> ({len(items)})")
            for item in items[:3]:
                title = item["title"][:140]
                summary = item.get("summary", "")
                line = f"  • <a href=\"{item['url']}\">{title}</a>"
                if summary and summary.lower() != "не критично":
                    line += f"\n    <i>💡 {summary}</i>"
                lines.append(line)
            lines.append("")
        msg = "\n".join(lines)

    # Telegram message limit: 4096 chars
    if len(msg) > 4000:
        msg = msg[:3950] + "\n\n…<i>(сводка обрезана)</i>"

    for chat_id in [c.strip() for c in chat_ids.split(",") if c.strip()]:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": msg,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )
            if r.status_code != 200:
                print(f"  Telegram {chat_id}: {r.status_code} {r.text[:200]}", flush=True)
            else:
                print(f"  Telegram {chat_id}: ok", flush=True)
        except Exception as e:
            print(f"  Telegram {chat_id} error: {e}", flush=True)

# ----------------------------- MAIN -----------------------------
def main():
    print(f"Run started: {dt.datetime.now(dt.timezone.utc).isoformat()}", flush=True)
    print(f"Tracking {len(COMPETITORS)} competitors, lookback {LOOKBACK_DAYS} days.", flush=True)

    news_by_competitor = {}
    for comp in COMPETITORS:
        items = fetch_news_for_competitor(comp)
        if items:
            news_by_competitor[comp["name"]] = items
        time.sleep(0.5)  # be kind to Google

    # Optional AI enrichment
    news_by_competitor = summarize_with_claude(news_by_competitor)

    # Save data file
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "total": sum(len(items) for items in news_by_competitor.values()),
        "by_competitor": news_by_competitor,
    }
    DATA_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {output['total']} items to {DATA_FILE}", flush=True)

    # Telegram
    send_telegram_digest(news_by_competitor)

    print("Done.", flush=True)

if __name__ == "__main__":
    main()
