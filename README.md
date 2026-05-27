# SR Competitive Intelligence Platform

Автоматическая система мониторинга Food Tech рынка Казахстана для команды Smart Restaurant by Choco.

**🎉 Полностью на бесплатных сервисах.** Никаких платных API, никаких подписок.

## Что делает каждый день

1. **📰 News scraper** — собирает упоминания 18+ конкурентов через Google News RSS (за последние 7 дней).
2. **💰 Vendor scraper** — ходит на сайты вендоров (iiko, Choice QR, QRPay, Starter, Wolt, Yandex Eats, Kaspi и т.д.), парсит цены/тарифы/фичи через регулярки и keyword-matching.
3. **🔔 Change detector** — сравнивает с вчерашним снимком, находит: новые цены, движение цен, новые фичи, новые интеграции, изменения слогана.
4. **📱 Telegram digest** — шлёт сводку в канал команды.
5. **🌐 Live website** — обновляет JSON, GitHub Pages пересобирает сайт автоматически.

**Стек:** GitHub Pages + GitHub Actions cron + Python (feedparser, trafilatura, requests, PyYAML) + Telegram Bot API. **Стоимость: 0 ₸.**

## Структура репозитория

```
sr-monitor/
├── index.html                          # Дашборд (10+ вкладок: Live News, Live Prices, Changes, и т.д.)
├── data/
│   ├── news.json                       # Авто: упоминания в новостях
│   ├── vendors.json                    # Авто: цены и фичи вендоров
│   └── changes.json                    # Авто: лог изменений
├── scripts/
│   ├── update_competitors.py           # Phase 1: News fetcher
│   ├── scrape_vendors.py               # Phase 2: Vendor scraper (heuristic)
│   ├── vendors.yaml                    # Список вендоров для скрейпинга
│   └── requirements.txt
├── .github/workflows/
│   └── daily.yml                       # Cron + ручной запуск
└── README.md                           # Этот файл
```

---

## Шаг 1. Создать GitHub-репозиторий

1. github.com → **+** → **New repository**
2. Имя: `sr-monitor` · **Public** · «Add a README file» · **Create**

## Шаг 2. Загрузить файлы

Перетащите все файлы из этой папки (с подпапками `data/`, `scripts/`, `.github/workflows/`) через **Add file → Upload files**. Не забудьте переименовать `smart_restaurant_competitive_kz.html` в `index.html`.

## Шаг 3. Включить GitHub Pages

Settings → Pages → Source: Deploy from a branch, branch `main`, folder `/(root)` → Save. Подождать 1–2 минуты.

## Шаг 4. Telegram-бот

1. В Telegram найдите **@BotFather** → `/newbot` → дайте имя и username
2. Получите **токен**

## Шаг 5. Узнать chat_id

Напишите боту любое сообщение → откройте `https://api.telegram.org/bot<ТОКЕН>/getUpdates` → найдите `"chat":{"id": …}`.

Для канала: добавьте бота админом → пошлите туда сообщение → ID будет отрицательным.

## Шаг 6. Секреты в репозитории

Settings → Secrets and variables → Actions → **New repository secret**:

| Имя | Значение |
|-----|----------|
| `TELEGRAM_BOT_TOKEN` | Токен из шага 4 |
| `TELEGRAM_CHAT_IDS` | chat_id из шага 5 (через запятую если несколько) |

Это всё. Никаких других секретов не нужно для бесплатной версии.

## Шаг 7. Дать workflow право пушить

Settings → Actions → General → **Workflow permissions** → **Read and write permissions** → Save.

## Шаг 8. Запустить вручную для проверки

Actions → **Daily Competitor Update** → **Run workflow** → зелёная кнопка.

Через 3–5 минут:
- В репо появится коммит «🤖 Daily monitor update …»
- В Telegram придёт сводка
- На GitHub Pages URL во вкладках «📰 Live News», «💰 Live Prices», «🔔 Changes» появятся реальные данные

С этого момента система работает сама ежедневно в 10:00 Алматы (04:00 UTC).

---

## Как настраивать

**Добавить нового вендора:** `scripts/vendors.yaml` → добавить запись с `name`, `type`, `country`, `urls`.

**Изменить расписание:** `.github/workflows/daily.yml` → `cron: '0 4 * * *'` (в UTC).

**Изменить список новостных запросов:** `scripts/update_competitors.py` → массив `COMPETITORS`.

**Добавить ключевое слово функции:** `scripts/scrape_vendors.py` → словарь `FEATURE_KEYWORDS`.

**Добавить интеграцию-партнёра для отслеживания:** там же → массив `INTEGRATION_NAMES`.

## Что именно ищет heuristic-парсер

**Цены (regex):**
- KZT: `8 000 ₸/мес`, `от 27 300 ₸`, `4 590 тенге`
- USD: `$12`, `от $25`
- RUB: `3 000 руб/мес`, `1 500 ₽`
- EUR: `€25`

**Функции (keyword match):**
QR-меню · QR-оплата · POS / Касса · Учёт / ERP · Киоск самообслуживания · Лояльность / CRM · Своё приложение · Доставка · WhatsApp / SMS · Telegram-бот · Аналитика / Dashboard · Бронирование · AI / ML · Чаевые · Бесконтактный заказ

**Интеграции (mention detection):**
iiko · r_keeper · Poster · Paloma · 1С · Jowi · Quick Resto · Kaspi · Freedom · Halyk · Jusan · Wolt · Яндекс · Glovo · Apple Pay · Google Pay · ePay

**Изменения (diff):**
Новые цены · удалённые цены · новые фичи · новые интеграции · изменения слогана.

## Стоимость и лимиты

- **GitHub Pages** — бесплатно (1 GB / 100 GB трафика в месяц)
- **GitHub Actions** — бесплатно (2 000 минут/мес для public repo, нам нужно ~150 минут/мес)
- **Telegram Bot API** — бесплатно
- **Google News RSS** — бесплатно
- **feedparser / trafilatura / requests** — open-source

Итого: **0 ₸/мес**.

## Опционально: добавить AI-обогащение позже

Если в будущем захотите улучшить парсинг (LLM умнее регулярок для извлечения клиентов и анонсов):
1. Зарегистрируйтесь на console.anthropic.com → создайте API key → пополните баланс ($10 хватит на 3+ месяца)
2. Settings → Secrets → добавьте `ANTHROPIC_API_KEY`
3. Перезапустите workflow — скрипт автоматически подхватит ключ и начнёт дополнительно извлекать клиентов и новости через Claude Haiku

Никаких изменений в коде не нужно — скрипт сам определит наличие ключа.

## Ограничения

- **Точность парсинга цен** ~75-85%: бывают ложные срабатывания на годы, артикулы, телефоны. Можно дообучить регулярки.
- **JS-only сайты** (Choice QR частично): скрейпер не выполняет JavaScript. Большинство KZ-вендоров отдают цены в HTML.
- **Instagram/Facebook посты не парсятся напрямую** — только через Google News, который индексирует часть постов.
- **Раз в 2–3 месяца** что-то может сломаться (вендоры меняют сайты) — нужна поддержка.

## Если что-то не работает

- **Action упал** — Actions → выберите запуск → раскройте шаги → читайте stdout
- **Vendor scraper не находит цены** — проверьте, что сайт реально открывается без JS (View source в браузере). Иначе нужен Playwright.
- **Telegram молчит** — секреты `TELEGRAM_*` без пробелов? Боту хоть раз писали `/start`?
- **404 на странице** — Pages включаются 1–2 минуты после Save
- **Workflow не коммитит** — Settings → Actions → General → Workflow permissions = Read and write
