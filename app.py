import os, time, requests, threading
from flask import Flask
from datetime import datetime

app = Flask(__name__)
SYMBOL = "BTCUSDT"
balance = 10.0
start_balance = 10.0
wins = 0
losses = 0
trades = 0
open_pos = None
last_signal = "Starting..."
last_price = 0
trend_1h = "RANGE"
ema50_1h = 0
ema200_1h = 0
logs = []
pending_reversal = "None"

# TELEGRAM - Put your Token and Chat ID for Render Env Vars
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}", flush=True)

def log(msg):
    t = datetime.now().strftime("%H:%M:%S")
    logs.append(f"{t}: {msg}")
    if len(logs) > 100:
        logs.pop(0)
    print(f"{t}: {msg}", flush=True)

def get_klines(interval, limit=250):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    tries = [
        ("https://api.bytick.com/v5/market/kline",
