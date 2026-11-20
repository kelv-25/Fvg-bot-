import os, time, requests, threading
from flask import Flask
from datetime import datetime
app = Flask(__name__)
SYMBOL = "BTCUSDT"
balance = 10.0
start_balance = 10.0
day_start_balance = 10.0
daily_profit = 0.0
wins = 0
losses = 0
trades = 0
wins_today = 0
trades_today = 0
last_day = datetime.now().day
open_pos = None
last_signal = "Starting SCALP..."
last_price = 0
logs = []
pending_fvg = None
pending_count = 0
last_sweep = "None yet"
MAX_WINS_DAILY = 10
TARGET_PROFIT_DAILY = 20.0
stopped_today = False
manual_continue = False
telegram_offset = 0
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        u = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
        requests.post(u, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except:
        pass

def log(msg):
    t = datetime.now().strftime("%H:%M:%S")
    logs.append(f"{t}: {msg}")
    if len(logs) > 100:
        logs.pop(0)
    print(f"{t}: {msg}", flush=True)

def telegram_listener():
    global telegram_offset, stopped_today, manual_continue, wins_today, day_start_balance, daily_profit
    while True:
        try:
            if not TELEGRAM_TOKEN:
                time.sleep(30)
                continue
            u = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            r = requests.get(u, params={"offset": telegram_offset, "timeout": 10}, timeout=15)
            data = r.json()
            if data.get("ok"):
                for upd in data.get("result", []):
                    telegram_offset = upd["update_id"] + 1
                    msg = upd.get("message", {})
                    text = msg.get("text", "").lower().strip()
                    if "continue" in text:
                        stopped_today = False
                        manual_continue = True
                        wins_today = 0
                        day_start_balance = balance
                        daily_profit = 0
                        send_telegram(f"▶️ CONTINUE - Resuming SCALP\nBalance: ${balance:.2f}")
                    elif "stop" in text:
                        stopped_today = True
                        manual_continue = False
                        send_telegram("⏸️ STOP - Paused. Send 'continue' to resume")
                    elif "status" in text:
                        send_telegram(f"📊 SCALP STATUS\nBalance: ${balance:.2f}\nDaily: ${daily_profit:+.2f}/$20\nWins: {wins_today}/10 Trades: {trades_today}\nLast Sweep: {last_sweep}")
            time.sleep(5)
        except:
            time.sleep(10)

def get_klines(interval, limit=100):
    headers = {"User-Agent": "Mozilla/5.0"}
    url1 = "https://api.bytick.com/v5/market/kline"
    p1 = {"category": "linear", "symbol": SYMBOL, "interval": interval, "limit": limit}
    try:
        r = requests.get(url1, params=p1, headers=headers, timeout=10)
        data = r.json()
        if data.get("retCode") == 0:
            out = []
            for c in reversed(data["result"]["list"]):
                out.append({"open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4])})
            return out
    except:
        pass
    url2 = "https://api.binance.us/api/v3/klines"
    iv = interval + "m"
    p2 = {"symbol": SYMBOL, "interval": iv, "limit": limit}
    try:
        r = requests.get(url2, params=p2, headers=headers, timeout=10)
        data = r.json()
        out = []
        for c in data:
            out.append({"open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4])})
        return out
    except Exception as e:
        raise Exception(f"Feed failed: {e}")

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

def detect_sweep(candles):
    if len(candles) < 25:
        return None
    recent = candles[-25:-5]
    last_5 = candles[-5:]
    swing_high = max(c["high"] for c in recent)
    swing_low = min(c["low"] for c in recent)
    for c in last_5:
        if c["high"] > swing_high and c["close"] < swing_high:
            return {"type": "BEARISH_SWEEP", "wick": c["high"], "level": swing_high}
        if c["low"] < swing_low and c["close"] > swing_low:
            return {"type": "BULLISH_SWEEP", "wick": c["low"], "level": swing_low}
    return None

def bot_loop():
    global balance, wins, losses, trades, wins_today, trades_today, last_day, open_pos, last_signal, pending_fvg, pending_count, stopped_today, manual_continue, day_start_balance, daily_profit, last_price, last_sweep
    log("SCALP started - 1M - Sweep OPTIONAL")
    send_telegram("🤖 SCALP Started - 1M\nSweep OPTIONAL - Trade with or without sweep\nSL behind sweep if sweep dey, else behind FVG\nStop: 10 wins + $20")
    while True:
        try:
            today = datetime.now().day
            if today != last_day:
                last_day = today
                wins_today = 0
                trades_today = 0
                day_start_balance = balance
                daily_profit = 0
                stopped_today = False
                manual_continue = False
            m1 = get_klines("1", 50)
            price = m1[-1]["close"]
            last_price = price
            last_candle = m1[-1]
            daily_profit = balance - day_start_balance
            sweep_now = detect_sweep(m1)
            if sweep_now:
                last_sweep = sweep_now["type"]
            last_signal = f"SCALP 1M - Price ${price:.2f} Sweep: {last_sweep} Wins {wins_today}/10 Daily ${daily_profit:+.2f}/$20"
            if open_pos:
                if open_pos["side"] == "BUY":
                    if price >= open_pos["tp"]:
                        profit = open_pos["risk"] * 2
                        balance += profit
                        wins += 1
                        wins_today += 1
                        trades += 1
                        trades_today += 1
                        daily_profit = balance - day_start_balance
                        open_pos = None
                        if wins_today >= MAX_WINS_DAILY and daily_profit >= TARGET_PROFIT_DAILY:
                            stopped_today = True
                            manual_continue = False
                            send_telegram(f"🟢 CLOSED - WIN BUY\nProfit: +${profit:.2f}\nBalance: ${balance:.2f}\n🏆 TARGET: {wins_today} wins + ${daily_profit:.2f}\nSTOPPED - Send 'continue'")
                        else:
                            send_telegram(f"🟢 CLOSED - WIN BUY\nProfit: +${profit:.2f}\nBalance: ${balance:.2f}\nWins: {wins_today}/10 Daily: ${daily_profit:+.2f}/$20")
                    elif price <= open_pos["sl"]:
                        loss = open_pos["risk"]
                        balance -= loss
                        losses += 1
                        trades += 1
                        trades_today += 1
                        daily_profit = balance - day_start_balance
                        open_pos = None
                        send_telegram(f"🟢 CLOSED - LOSS BUY\nLoss: -${loss:.2f}\nBalance: ${balance:.2f}\nWins: {wins_today}/10 Daily: ${daily_profit:+.2f}/$20")
                else:
                    if price <= open_pos["tp"]:
                        profit = open_pos["risk"] * 2
                        balance += profit
                        wins += 1
                        wins_today += 1
                        trades += 1
                        trades_today += 1
                        daily_profit = balance - day_start_balance
                        open_pos = None
                        if wins_today >= MAX_WINS_DAILY and daily_profit >= TARGET_PROFIT_DAILY:
                            stopped_today = True
                            manual_continue = False
                            send_telegram(f"🟢 CLOSED - WIN SELL\nProfit: +${profit:.2f}\nBalance: ${balance:.2f}\n🏆 TARGET: {wins_today} wins + ${daily_profit:.2f}\nSTOPPED - Send 'continue'")
                        else:
                            send_telegram(f"🟢 CLOSED - WIN SELL\nProfit: +${profit:.2f}\nBalance: ${balance:.2f}\nWins: {wins_today}/10 Daily: ${daily_profit:+.2f}/$20")
                    elif price >= open_pos["sl"]:
                        loss = open_pos["risk"]
                        balance -= loss
                        losses += 1
                        trades += 1
                        trades_today += 1
                        daily_profit = balance - day_start_balance
                        open_pos = None
                        send_telegram(f"🟢 CLOSED - LOSS SELL\nLoss: -${loss:.2f}\nBalance: ${balance:.2f}\nWins: {wins_today}/10 Daily: ${daily_profit:+.2f}/$20")
                time.sleep(10)
                continue
            if stopped_today and not manual_continue:
                last_signal = f"🏆 TARGET HIT - Send 'continue' to resume"
                time.sleep(30)
                continue
            if pending_fvg:
                pending_count += 1
                if pending_count > 4:
                    pending_fvg = None
                    pending_count = 0
                    time.sleep(10)
                    continue
                fvg = pending_fvg
                sweep = pending_fvg.get("sweep")
                confirmed = False
                if fvg["type"] == "BULLISH":
                    touched = last_candle["low"] <= fvg["top"]
                    bullish_close = last_candle["close"] > last_candle["open"]
                    above_zone = last_candle["close"] > fvg["bottom"]
                    if touched and bullish_close and above_zone:
                        confirmed = True
                else:
                    touched = last_candle["high"] >= fvg["bottom"]
                    bearish_close = last_candle["close"] < last_candle["open"]
                    below_zone = last_candle["close"] < fvg["top"]
                    if touched and bearish_close and below_zone:
                        confirmed = True
                if not confirmed:
                    time.sleep(10)
                    continue
                side = "BUY" if fvg["type"] == "BULLISH" else "SELL"
                buffer = price * 0.0002
                if side == "BUY":
                    entry = price
                    if sweep and sweep["type"] == "BULLISH_SWEEP":
                        sl = min(fvg["bottom"], sweep["wick"] - buffer)
                        sl_note = "behind sweep wick"
                    else:
                        sl = fvg["bottom"] - buffer
                        sl_note = "behind FVG (no sweep)"
                    if sl >= entry:
                        pending_fvg = None
                        continue
                    tp = entry + (entry - sl) * 2
                else:
                    entry = price
                    if sweep and sweep["type"] == "BEARISH_SWEEP":
                        sl = max(fvg["top"], sweep["wick"] + buffer)
                        sl_note = "behind sweep wick"
                    else:
                        sl = fvg["top"] + buffer
                        sl_note = "behind FVG (no sweep)"
                    if sl <= entry:
                        pending_fvg = None
                        continue
                    tp = entry - (sl - entry) * 2
                risk = balance * 0.10
                sl_dist = abs(entry - sl) / entry
                if sl_dist == 0 or sl_dist > 0.01:
                    log("Skip - SL too wide")
                    pending_fvg = None
                    continue
                size = risk / sl_dist
                open_pos = {"side": side, "entry": entry, "sl": sl, "tp": tp, "size": size, "risk": risk}
                log(f"OPEN {side} @ ${entry:.2f} SL ${sl:.2f} ({sl_note}) TP ${tp:.2f}")
                send_telegram(f"🔴 ENTERED - {side} SCALP\nEntry: ${entry:.2f}\nSL: ${sl:.2f} ({sl_note})\nTP: ${tp:.2f}\nRisk: ${risk:.2f} Win: +${risk*2:.2f}\nWins: {wins_today}/10 Daily: ${daily_profit:+.2f}/$20")
                pending_fvg = None
                pending_count = 0
                time.sleep(10)
                continue
            fvg = find_fvg(m1)
            if not fvg:
                time.sleep(10)
                continue
            fvg["sweep"] = sweep_now
            pending_fvg = fvg
            pending_count = 0
            if sweep_now:
                log(f"FVG {fvg['type']} + SWEEP {sweep_now['type']} - Waiting Retest")
                send_telegram(f"👀 FVG {fvg['type']} + SWEEP {sweep_now['type']}\nWaiting Retest\nPrice: ${price:.2f}")
            else:
                log(f"FVG {fvg['type']} (no sweep) - Still trading - Waiting Retest")
                send_telegram(f"👀 FVG {fvg['type']} (No Sweep) - Still Trading\nWaiting Retest\nPrice: ${price:.2f}")
            time.sleep(10)
        except Exception as e:
            log(f"Error: {e}")
            time.sleep(10)

@app.route("/")
def home():
    if open_pos:
        pos_color = "#ff4444" if open_pos["side"] == "SELL" else "#00c853"
        pos_html = f"<div style='background:{pos_color};padding:12px;border-radius:10px'>🔴 LIVE {open_pos['side']} @ ${open_pos['entry']:.2f}<br>SL ${open_pos['sl']:.2f} TP ${open_pos['tp']:.2f}<br>Risk ${open_pos['risk']:.2f} Win +${open_pos['risk']*2:.2f}</div>"
    else:
        pend = f"👀 Waiting: {pending_fvg['type']} FVG" if pending_fvg else "⚪ Scanning 1M - Waiting FVG..."
        pos_html = f"<div style='background:#2a2a2a;padding:12px;border-radius:10px'>{pend}</div>"
    profit = balance - start_balance
    profit_color = "#00c853" if profit >= 0 else "#ff4444"
    daily_color = "#00c853" if daily_profit >= 0 else "#ff4444"
    winrate = 0
    if trades > 0:
        winrate = wins / trades * 100
    stop_txt = "🏆 STOPPED - Send 'continue' on Telegram" if stopped_today else "🟢 SCALPING - LIVE"
    logs_html = "<br>".join(logs[-40:])
    return f"<body style='background:#0f0f0f;color:#fff;font-family:sans-serif;padding:15px'><h2 style='color:#00e5ff'>⚡ SCALP - 1M - SWEEP OPTIONAL</h2><p style='color:#ffab00'>{stop_txt} | Last Sweep: {last_sweep}</p><div style='display:flex;gap:10px'><div style='background:#1e1e1e;padding:12px;border-radius:10px;flex:1'><small>BALANCE</small><h2>${balance:.2f}</h2><span style='color:{profit_color}'>Total: ${profit:+.2f}</span><br><span style='color:{daily_color}'>Today: ${daily_profit:+.2f} / $20</span></div><div style='background:#1e1e1e;padding:12px;border-radius:10px;flex:1'><small>WINS TODAY</small><h2>{wins_today}/10 🏆</h2><span style='color:#00c853'>🟢 {wins} Win</span> <span style='color:#ff4444'>🔴 {losses} Loss</span><br>WinRate: {winrate:.0f}% Trades Today: {trades_today}</div></div><p>Price ${last_price:.2f} | {last_signal}</p><h3>Open Position</h3>{pos_html}<h3>Logs</h3><div style='background:#1e1e1e;padding:10px;border-radius:10px;font-size:13px'>{logs_html}</div><script>setTimeout(()=>location.reload(),10000)</script></body>"

threading.Thread(target=telegram_listener, daemon=True).start()
threading.Thread(target=bot_loop, daemon=True).start()
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)
