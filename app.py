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

def log(msg):
    t = datetime.now().strftime("%H:%M:%S")
    logs.append(f"{t}: {msg}")
    if len(logs) > 100:
        logs.pop(0)
    print(f"{t}: {msg}", flush=True)

def get_klines(interval, limit=250):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    # 1 = Bybit bytick (best for Render), 2 = Bybit main, 3 = Binance US backup
    tries = [
        ("https://api.bytick.com/v5/market/kline", {"category": "linear", "symbol": SYMBOL, "interval": interval, "limit": limit}, "bybit"),
        ("https://api.bybit.com/v5/market/kline", {"category": "linear", "symbol": SYMBOL, "interval": interval, "limit": limit}, "bybit"),
        ("https://api.binance.us/api/v3/klines", {"symbol": SYMBOL, "interval": "1h" if interval == "60" else interval + "m", "limit": limit}, "binanceus"),
    ]
    last_err = ""
    for url, p, kind in tries:
        try:
            r = requests.get(url, params=p, headers=headers, timeout=10)
            if "text/html" in r.headers.get("Content-Type", ""):
                last_err = "HTML"
                continue
            data = r.json
