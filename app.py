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
            data = r.json()
            if kind == "bybit":
                if data.get("retCode") != 0:
                    last_err = str(data)
                    continue
                out = []
                for c in reversed(data["result"]["list"]):
                    out.append({"open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4])})
                return out
            else:
                out = []
                for c in data:
                    out.append({"open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4])})
                return out
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
    a = candles[-3]
    c = candles[-1]
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
    global balance, wins, losses, trades, open_pos, last_signal
    log("Bot started - Bybit feed")
    while True:
        try:
            if not check_trend():
                time.sleep(30)
                continue
            m15 = get_klines("15", 50)
            price = m15[-1]["close"]
            last_signal = f"Scanning - Price ${price:.2f} Trend {trend_1h}"
            log(f"Scan: Price ${price:.2f} Trend {trend_1h} EMA50 {ema50_1h:.2f} EMA200 {ema200_1h:.2f}")
            if open_pos:
                if open_pos["side"] == "BUY":
                    if price >= open_pos["tp"]:
                        profit = open_pos["size"] * (open_pos["tp"] - open_pos["entry"]) / open_pos["entry"]
                        balance += profit; wins += 1; trades += 1
                        log(f"WIN BUY +${profit:.2f} Balance ${balance:.2f}")
                        open_pos = None
                    elif price <= open_pos["sl"]:
                        loss = open_pos["size"] * (open_pos["entry"] - open_pos["sl"]) / open_pos["entry"]
                        balance -= loss; losses += 1; trades += 1
                        log(f"LOSS BUY -${loss:.2f} Balance ${balance:.2f}")
                        open_pos = None
                else:
                    if price <= open_pos["tp"]:
                        profit = open_pos["size"] * (open_pos["entry"] - open_pos["tp"]) / open_pos["entry"]
                        balance += profit; wins += 1; trades += 1
                        log(f"WIN SELL +${profit:.2f} Balance ${balance:.2f}")
                        open_pos = None
                    elif price >= open_pos["sl"]:
                        loss = open_pos["size"] * (open_pos["sl"] - open_pos["entry"]) / open_pos["entry"]
                        balance -= loss; losses += 1; trades += 1
                        log(f"LOSS SELL -${loss:.2f} Balance ${balance:.2f}")
                        open_pos = None
                time.sleep(30)
                continue
            fvg = find_fvg(m15)
            if not fvg:
                time.sleep(30)
                continue
            side = None
            if trend_1h == "UPTREND" and fvg["type"] == "BULLISH":
                side = "BUY"
            elif trend_1h == "DOWNTREND" and fvg["type"] == "BEARISH":
                side = "SELL"
            else:
                log(f"Skip FVG {fvg['type']} - Trend {trend_1h} no agree")
                time.sleep(30)
                continue
            risk = balance * 0.02
            size = risk * 50
            if side == "BUY":
                entry = price; sl = fvg["bottom"]; tp = entry + (entry - sl) * 2
                if sl >= entry:
                    continue
            else:
                entry = price; sl = fvg["top"]; tp = entry - (sl - entry) * 2
                if sl <= entry:
                    continue
            open_pos = {"side": side, "entry": entry, "sl": sl, "tp": tp, "size": size}
            last_signal = f"{side} @ ${entry:.2f}"
            log(f"OPEN {side} @ ${entry:.2f} SL ${sl:.2f} TP ${tp:.2f} FVG {fvg['type']} Trend {trend_1h}")
            time.sleep(30)
        except Exception as e:
            log(f"Error: {e}")
            time.sleep(30)

@app.route("/")
def home():
    pos_html = "None" if not open_pos else f"{open_pos['side']} @ ${open_pos['entry']:.2f} SL ${open_pos['sl']:.2f} TP ${open_pos['tp']:.2f}"
    logs_html = "<br>".join(logs[-40:])
    return f"""<body style="background:#111;color:#fff;font-family:sans-serif;padding:15px"><h3>🤖 FVG + EMA Bot Monitor - SMART - BYBIT</h3><p>Status: LIVE - Bybit Feed | Last Update: {datetime.now().strftime('%H:%M:%S')}</p><p><b>Paper Balance</b><br>${balance:.2f}<br>Start: ${start_balance} | Trades: {trades} | Wins: {wins} | Losses: {losses}</p><p><b>TREND (1H): {trend_1h}</b> | 1H Price: ${last_price:.2f} | 1H EMA50: ${ema50_1h:.2f} | 1H EMA200: ${ema200_1h:.2f} | Last Signal: {last_signal}<br>Pending Reversal: {pending_reversal}</p><p><b>Open Position</b><br>{pos_html}</p><p><b>Logs</b><br>{logs_html}</p><script>setTimeout(()=>location.reload(),30000)</script></body>"""

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)
