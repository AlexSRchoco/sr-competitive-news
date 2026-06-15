#!/usr/bin/env python3
"""
Lightweight Telegram bot poller.

Runs every 15 minutes via GitHub Actions:
  1. Fetches new messages from Telegram (getUpdates)
  2. Processes /start /stop /help commands → subscribes / unsubscribes
  3. Treats other messages as queries → searches data → responds

This is the "interactive Q&A" backend.
"""
from pathlib import Path
from telegram_subs import process_commands

ROOT = Path(__file__).resolve().parent.parent
SUBS_FILE = ROOT / "data" / "subscribers.json"

if __name__ == "__main__":
    process_commands(SUBS_FILE)
