import os, time, requests, threading
from flask import Flask
from datetime import datetime

app = Flask(__name__)

# ===== CONFIG =====
SYMBOL = "BTCUSDT"
PAPER_BALANCE = 10.0
RISK_PCT = 0.02
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT", "")

balance = PAPER_BALANCE
start_balance = PAPER_BALANCE
wins = 0
losses = 0
trades = 0
open_pos = None
last_signal = "None"
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
    print(f"{t}: {msg}")

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": TELEGRAM_CHAT, "text": msg}, timeout=5)
    except Exception as e:
        log(f"Telegram error: {e}")

# ===== RECTIFIED DATA FEED =====
def get_klines(interval, limit=250):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    params = {"category": "linear", "symbol": SYMBOL, "interval": interval, "limit": limit}

    # Door 1: Bytick - Best for Render US
    # Door 2: Bybit main
    # Door 3: Binance.US - backup, e support US IP
    tries = [
        ("https://api.bytick.com/v5/market/kline", params, "bybit"),
        ("https://api.bybit.com/v5/market/kline", params, "bybit"),
        ("https://api.binance.us/api/v3/klines", {"symbol": SYMBOL, "interval": interval + "m" if interval != "60" else "1h", "limit": limit}, "binanceus"),
    ]

    last_err = ""
    for url, p, kind in tries:
        try:
            r = requests.get(url, params=p, headers=headers, timeout=10)
            if "text/html" in r.headers.get("Content-Type", ""):
                last_err = f"HTML from {url}"
                continue
            data = r.json()
            if kind == "bybit":
                if data.get("retCode") != 0:
                    last_err = str(data)
                    continue
                candles = []
                for c in reversed(data["result"]["list"]):
                    candles.append({"open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4])})
                return candles
            else:  # binance.us
                candles = []
                for c in data:
                    candles.append({"open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4])})
                return candles
        except Exception as e:
            last_err = str(e)
            continue
    raise Exception(f"All feeds failed: {last_err}")

def ema(candles, period):
    closes = [c["close"] for c in candles]
    if len(closes) < period:
        return closes[-1] if closes else 0
    k = 2 / (period + 1)
    e = sum(closes[:period]) / period
    for price in closes[period:]:
        e = price * k + e * (1 - k)
    return e

def find_fvg(candles):
    if len(candles) < 4:
        return None
    a, b, c = candles[-3], candles[-2], candles[-1]
    if c["low"] > a["high"]:
        return {"type": "BULLISH", "top": c["low"], "bottom": a["high"]}
    if c["high"] < a["low"]:
        return {"type": "BEARISH", "top": a["low"], "bottom": c["high"]}
    return None

def check_trend():
    global trend_1h, ema50_1h, ema200_1h, last_price
    try:
        h1 = get_klines("60", 250)
        last_price = h1[-1]["close"]
        ema50_1h = ema(h1, 50)
        ema200_1h = ema(h1, 200)
        if last_price > ema50_1h > ema200_1h:
            trend_1h = "UPTREND"
        elif last_price < ema50_1h < ema200_1h:
            trend_1h = "DOWNTREND"
        else:
            trend_1h = "RANGE"
        return True
    except Exception as e:
        log(f"Trend error: {e}")
        return False

def bot_loop():
    global balance, wins, losses, trades
