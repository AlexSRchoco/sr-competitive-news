#!/usr/bin/env python3
"""
SR Monitor — vendor scraper (FREE TIER, no paid APIs).

For each vendor in vendors.yaml:
  1. Fetch each URL (HTML).
  2. Extract main text content (trafilatura — free, Apache 2.0).
  3. Run heuristic extraction:
     - Regex for prices (₸, $, RUB, EUR with amounts)
     - Keyword matching for features (QR-меню, киоск, лояльность, etc.)
     - Detect company name mentions for integrations
  4. Compare with previous snapshot — flag changes.
  5. Save to ../data/vendors.json.

ZERO paid services. Uses only: feedparser, requests, trafilatura, PyYAML.

OPTIONAL: if ANTHROPIC_API_KEY is set, will ADDITIONALLY enrich with LLM extraction.
Without it — heuristic mode still works fully.
"""
import os
import re
import sys
import json
import time
import hashlib
import datetime as dt
from pathlib import Path

import yaml
import requests
import trafilatura

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "vendors.json"
CHANGES_FILE = ROOT / "data" / "changes.json"
VENDORS_CFG = Path(__file__).parent / "vendors.yaml"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SR-Monitor/1.0)",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8,kk;q=0.7",
}

# ============== HEURISTIC EXTRACTION ==============

# Regex для цен в KZT, USD, RUB, EUR
# Допускает: "8 000 ₸/мес", "от 27 300 ₸", "$12", "1 500 руб/мес", "€25"
PRICE_PATTERNS = [
    # KZT — основной для KZ-сайтов
    re.compile(r"(?:от\s+)?(\d{1,3}(?:[\s ]\d{3})*|\d+)\s*(?:₸|тенге|тг|KZT)[\s\.,;]*(?:в\s*месяц|/мес|/month|в\s*год|/year|единоразово|разово)?", re.IGNORECASE),
    # USD
    re.compile(r"(?:от\s+)?(?:\$|USD\s*)(\d{1,4}(?:[\s \.]\d{3})*(?:[\.,]\d+)?)[\s\.,;]*(?:в\s*месяц|/мес|/month|per\s+month)?", re.IGNORECASE),
    # RUB
    re.compile(r"(?:от\s+)?(\d{1,4}(?:[\s ]\d{3})*)\s*(?:руб(?:лей)?|₽|RUB)[\s\.,;]*(?:в\s*месяц|/мес|/month)?", re.IGNORECASE),
    # EUR
    re.compile(r"(?:от\s+)?(?:€|EUR\s*)(\d{1,4}(?:[\s \.]\d{3})*(?:[\.,]\d+)?)[\s\.,;]*(?:в\s*месяц|/мес|/month)?", re.IGNORECASE),
]
PRICE_CURRENCIES = ["KZT", "USD", "RUB", "EUR"]

# Регистр-нечувствительные ключевые слова для определения функций.
# Ключ — внутренний идентификатор, значение — список синонимов.
FEATURE_KEYWORDS = {
    "QR-меню": ["QR-меню", "QR меню", "электронное меню", "цифровое меню", "online menu", "qr-code menu"],
    "QR-оплата": ["оплата по QR", "QR-оплата", "QR pay", "split bill", "разделить счёт", "qr payment"],
    "POS / Касса": ["POS-система", "POS система", "касса", "кассовая система", "front-office", "кассовый аппарат"],
    "Учёт / ERP": ["складской учёт", "финансовый учёт", "ERP", "управление складом", "учёт прибыли"],
    "Киоск самообслуживания": ["киоск самообслуживания", "self-order", "self-service kiosk", "касса самообслуживания"],
    "Лояльность / CRM": ["программа лояльности", "лояльность", "CRM", "кешбек", "кэшбек", "бонусная система", "loyalty"],
    "Своё приложение": ["мобильное приложение", "white-label app", "брендированное приложение", "ios", "android"],
    "Доставка / Delivery": ["служба доставки", "доставка еды", "интеграция курьеров", "delivery integration", "своя доставка"],
    "WhatsApp / SMS": ["WhatsApp-рассылки", "WhatsApp", "SMS-рассылки", "push-уведомления"],
    "Telegram-бот": ["Telegram-бот", "telegram bot", "виртуальная карта в telegram"],
    "Аналитика / Dashboard": ["аналитика", "отчёты", "dashboard", "дашборд", "BI", "статистика продаж"],
    "Бронирование": ["бронирование столов", "бронирование столиков", "reservation", "резерв"],
    "AI / ML": ["AI", "искусственный интеллект", "ML", "машинное обучение", "нейросеть", "GPT", "Claude"],
    "Чаевые": ["чаевые", "tips", "оплата чаевых"],
    "Бесконтактный заказ": ["бесконтактный заказ", "заказ без официанта", "order without waiter"],
}

# Известные имена POS, с которыми вендор может интегрироваться
INTEGRATION_NAMES = ["iiko", "r_keeper", "r-keeper", "Poster", "Paloma", "1С", "Jowi", "Quick Resto",
                     "Kaspi", "Freedom", "Halyk", "Jusan", "Wolt", "Яндекс", "Yandex", "Glovo",
                     "Apple Pay", "Google Pay", "ePay"]


def fetch_url(url, timeout=20):
    """Fetch HTML; returns text or None."""
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.text
    except Exception as e:
        print(f"    fetch error {url}: {e}", flush=True)
        return None


def extract_text(html, url=None):
    """Use trafilatura to extract main content text."""
    if not html:
        return ""
    try:
        text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True, no_fallback=False)
        return text or ""
    except Exception:
        return ""


def normalize_number(s):
    """'8 000' -> 8000, '27 300.50' -> 27300.50"""
    if not s:
        return None
    cleaned = s.replace(" ", " ").replace(" ", "").replace(",", ".")
    try:
        # Если есть и точка как разделитель тысяч — убираем (например, '$1.299')
        if cleaned.count(".") > 1:
            parts = cleaned.split(".")
            cleaned = "".join(parts[:-1]) + "." + parts[-1]
        return float(cleaned) if "." in cleaned else int(cleaned)
    except Exception:
        return None


def extract_prices(text):
    """Return list of {'price_text': str, 'value_numeric': num, 'currency': str, 'context': str}."""
    results = []
    seen = set()  # dedup by (value, currency)
    for i, pattern in enumerate(PRICE_PATTERNS):
        currency = PRICE_CURRENCIES[i]
        for m in pattern.finditer(text):
            raw = m.group(0).strip()
            num = normalize_number(m.group(1))
            if num is None or num < 50:  # фильтруем слишком маленькие (вроде "$1")
                continue
            if currency == "KZT" and num < 500:
                continue
            key = (num, currency)
            if key in seen:
                continue
            seen.add(key)
            # 60 символов контекста до+после
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 60)
            context = text[start:end].replace("\n", " ").strip()
            results.append({
                "price_text": raw,
                "value_numeric": num,
                "currency": currency,
                "context": context[:160],
            })
    # Сортируем по цене и обрезаем до топ-15
    results.sort(key=lambda x: x["value_numeric"])
    return results[:15]


def extract_features(text):
    """Detect feature keywords. Returns list of canonical feature names."""
    text_lower = text.lower()
    found = []
    for canonical, synonyms in FEATURE_KEYWORDS.items():
        for syn in synonyms:
            if syn.lower() in text_lower:
                found.append(canonical)
                break
    return found


def extract_integrations(text):
    """Detect mentions of known integration partners."""
    found = []
    text_lower = text.lower()
    for name in INTEGRATION_NAMES:
        if name.lower() in text_lower and name not in found:
            found.append(name)
    return found


def extract_tagline(text):
    """First meaningful line of text — often the hero tagline."""
    if not text:
        return None
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # Skip pure-numeric lines and very short ones
    for line in lines[:10]:
        if 20 < len(line) < 200 and not line.replace(" ", "").isdigit():
            return line
    return lines[0][:200] if lines else None


# ============== OPTIONAL: LLM ENRICHMENT (only if API key present) ==============

def claude_enrich(vendor_name, text, api_key):
    """OPTIONAL: enrich with LLM. Returns dict or None. Only called if api_key set."""
    if not api_key or not text.strip():
        return None
    text = text[:10000]
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
                "max_tokens": 1024,
                "messages": [{
                    "role": "user",
                    "content": f"""Извлеки клиентов и последние новости с этой страницы вендора «{vendor_name}». Ответь JSON: {{"notable_clients": [...до 5 названий ресторанов-клиентов...], "recent_news_or_changes": "одна строка или null"}}. Только то, что явно написано на странице.

Текст:
{text}"""
                }],
            },
            timeout=60,
        )
        if resp.status_code != 200:
            return None
        content = resp.json()["content"][0]["text"].strip()
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            return json.loads(content[start:end+1])
    except Exception as e:
        print(f"    Claude enrich failed: {e}", flush=True)
    return None


# ============== MAIN SCRAPE LOOP ==============

def scrape_vendor(vendor, api_key=None):
    name = vendor["name"]
    print(f"  → {name}", flush=True)
    raw_texts = []
    fetched_urls = []
    for url in vendor.get("urls", []):
        html = fetch_url(url)
        if not html:
            continue
        txt = extract_text(html, url)
        if txt:
            raw_texts.append(txt[:6000])
            fetched_urls.append(url)
        time.sleep(0.7)

    combined = "\n\n".join(raw_texts)
    snapshot_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16] if combined else None

    # Heuristic extraction
    extracted = {
        "tagline": extract_tagline(combined) if combined else None,
        "pricing_tiers": extract_prices(combined),
        "features": extract_features(combined),
        "integrations": extract_integrations(combined),
        "notable_clients": [],
        "recent_news_or_changes": None,
    }

    # Optional LLM enrichment for clients + news (only if API key set)
    if combined and api_key:
        enriched = claude_enrich(name, combined, api_key)
        if enriched:
            if enriched.get("notable_clients"):
                extracted["notable_clients"] = enriched["notable_clients"]
            if enriched.get("recent_news_or_changes"):
                extracted["recent_news_or_changes"] = enriched["recent_news_or_changes"]

    record = {
        "name": name,
        "type": vendor.get("type"),
        "country": vendor.get("country"),
        "urls": vendor.get("urls", []),
        "social": vendor.get("social", {}),
        "last_checked": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fetched_urls": fetched_urls,
        "snapshot_hash": snapshot_hash,
        "text_excerpt": combined[:600] if combined else None,
        "extracted": extracted,
    }
    return record


def diff_vendors(old, new):
    """Return list of human-readable change strings."""
    changes = []
    new_idx = {v["name"]: v for v in new}
    old_idx = {v["name"]: v for v in old} if old else {}

    for name, n_rec in new_idx.items():
        o_rec = old_idx.get(name)
        if not o_rec:
            changes.append(f"➕ Новый вендор в трекере: {name}")
            continue
        if o_rec.get("snapshot_hash") == n_rec.get("snapshot_hash"):
            continue

        o_ex = o_rec.get("extracted") or {}
        n_ex = n_rec.get("extracted") or {}

        # Price changes — сравниваем по числовому значению + валюте
        o_prices = {(p.get("value_numeric"), p.get("currency")): p for p in (o_ex.get("pricing_tiers") or [])}
        n_prices = {(p.get("value_numeric"), p.get("currency")): p for p in (n_ex.get("pricing_tiers") or [])}
        for key, n_p in n_prices.items():
            if key not in o_prices:
                changes.append(f"💰 {name}: новая цена «{n_p.get('price_text','?')}»")
        for key, o_p in o_prices.items():
            if key not in n_prices:
                changes.append(f"❌ {name}: цена «{o_p.get('price_text','?')}» исчезла со страницы")

        # New features
        o_feats = set(o_ex.get("features") or [])
        n_feats = set(n_ex.get("features") or [])
        for f in (n_feats - o_feats):
            changes.append(f"✨ {name}: новая фича — {f}")
        for f in (o_feats - n_feats):
            changes.append(f"➖ {name}: убрали упоминание — {f}")

        # New integrations
        o_int = set(o_ex.get("integrations") or [])
        n_int = set(n_ex.get("integrations") or [])
        for i in (n_int - o_int):
            changes.append(f"🔌 {name}: новая интеграция — {i}")

        # Tagline change
        if o_ex.get("tagline") and n_ex.get("tagline") and o_ex["tagline"][:100] != n_ex["tagline"][:100]:
            changes.append(f"📣 {name}: изменился заголовок страницы")

        # Catch-all if hash differs but nothing else detected
        if o_rec.get("snapshot_hash") != n_rec.get("snapshot_hash"):
            recent_changes = [c for c in changes if name in c]
            if not recent_changes:
                changes.append(f"🔄 {name}: контент изменился (детали не извлечены heuristic-парсером)")

    return changes


def send_telegram_changes(change_list, today_iso):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = os.environ.get("TELEGRAM_CHAT_IDS", "").strip()
    if not token or not chat_ids or not change_list:
        return
    msg = f"<b>🔔 SR Monitor — изменения у конкурентов · {today_iso}</b>\n\n"
    msg += "\n".join(f"• {c}" for c in change_list[:25])
    if len(change_list) > 25:
        msg += f"\n\n…ещё {len(change_list)-25} изменений (см. сайт)"
    if len(msg) > 4000:
        msg = msg[:3950] + "\n\n…(обрезано)"
    for chat_id in [c.strip() for c in chat_ids.split(",") if c.strip()]:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=30,
            )
        except Exception as e:
            print(f"  Telegram error: {e}", flush=True)


def main():
    print(f"Vendor scrape started: {dt.datetime.now(dt.timezone.utc).isoformat()}", flush=True)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        print("ANTHROPIC_API_KEY found — будет также делать enrichment (клиенты, новости).", flush=True)
    else:
        print("Работаем в FREE-режиме (heuristic-парсинг, без API).", flush=True)

    cfg = yaml.safe_load(VENDORS_CFG.read_text(encoding="utf-8"))
    vendor_list = cfg.get("vendors", [])
    print(f"Scanning {len(vendor_list)} vendors...", flush=True)

    # Load previous
    old_vendors = []
    if DATA_FILE.exists():
        try:
            old_data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            old_vendors = old_data.get("vendors", [])
        except Exception:
            pass

    new_vendors = []
    for vendor in vendor_list:
        try:
            rec = scrape_vendor(vendor, api_key)
            new_vendors.append(rec)
        except Exception as e:
            print(f"    failed {vendor['name']}: {e}", flush=True)

    change_list = diff_vendors(old_vendors, new_vendors)
    today_iso = dt.date.today().isoformat()

    # Save vendors.json
    output = {
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "vendor_count": len(new_vendors),
        "mode": "ai-enriched" if api_key else "heuristic-only",
        "vendors": new_vendors,
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(new_vendors)} vendors → {DATA_FILE}", flush=True)

    # Append changes
    changes_log = {"days": []}
    if CHANGES_FILE.exists():
        try:
            changes_log = json.loads(CHANGES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    if change_list:
        existing = [d for d in changes_log.get("days", []) if d.get("date") == today_iso]
        if existing:
            existing[0]["changes"] = change_list
        else:
            changes_log.setdefault("days", []).insert(0, {"date": today_iso, "changes": change_list})
        changes_log["days"] = changes_log["days"][:60]
    CHANGES_FILE.write_text(json.dumps(changes_log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Detected {len(change_list)} changes → {CHANGES_FILE}", flush=True)

    send_telegram_changes(change_list, today_iso)
    print("Vendor scrape done.", flush=True)


if __name__ == "__main__":
    main()
