import ccxt, pandas as pd, requests, time, datetime, threading, os
from flask import Flask, jsonify, render_template_string

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SYMBOL = "BTC/USDT"
TIMEFRAME = "15m"
PAPER_BALANCE = 10.0
RISK_PCT = 0.10

exchange = ccxt.binance({'enableRateLimit': True})

state = {"status":"starting","balance":PAPER_BALANCE,"price":0,"ema50":0,"ema200":0,"position":None,"total_trades":0,"wins":0,"losses":0,"last_signal":"None","last_update":"Never","logs":[]}

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    state["logs"] = ([entry] + state["logs"])[:50]
    print(entry)
    state["last_update"] = ts

def tg(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        log(f"TG error: {e}")

def get_df():
    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=250)
    df = pd.DataFrame(ohlcv, columns=['t','open','high','low','close','vol'])
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    return df

def check_fvg(df):
    c1 = df.iloc[-4]
    c3 = df.iloc[-2]
    price = df.iloc[-1]['close']
    ema50 = df.iloc[-1]['ema50']
    ema200 = df.iloc[-1]['ema200']
    if c1['high'] < c3['low']:
        if price > ema50 and ema50 > ema200:
            return "BUY", c3['low'], c1['high'], price
    if c1['low'] > c3['high']:
        if price < ema50 and ema50 < ema200:
            return "SELL", c1['low'], c3['high'], price
    return None, None, None, price

def bot_loop():
    balance = PAPER_BALANCE
    position = None
    log("Bot loop started")
    tg(f"🤖 *FVG BOT LIVE WITH MONITOR*\nPair: {SYMBOL}\nPaper: ${balance}")
    state["status"] = "RUNNING"
    while True:
        try:
            df = get_df()
            signal, gap_top, gap_bottom, price = check_fvg(df)
            state["price"] = round(float(price), 2)
            state["ema50"] = round(float(df.iloc[-1]['ema50']), 2)
            state["ema200"] = round(float(df.iloc[-1]['ema200']), 2)
            state["balance"] = round(balance, 2)
            state["position"] = position
            state["last_signal"] = signal or "No FVG"
            log(f"Price {price:.2f} | Sig {signal} | Bal ${balance:.2f}")
            if position:
                if position['side'] == 'BUY':
                    if price <= position['sl']:
                        loss = (position['entry'] - position['sl']) * position['size']
                        balance -= loss
                        state["total_trades"] += 1; state["losses"] += 1
                        tg(f"❌ *CLOSED - LOSS*\nPair: {SYMBOL}\nLONG\nEntry: {position['entry']:.2f}\nExit: {price:.2f}\nLoss: -${loss:.2f}\nBalance: ${balance:.2f}")
                        position = None
                    elif price >= position['tp']:
                        profit = (position['tp'] - position['entry']) * position['size']
                        balance += profit
                        state["total_trades"] += 1; state["wins"] += 1
                        tg(f"✅ *CLOSED - WIN*\nPair: {SYMBOL}\nLONG\nEntry: {position['entry']:.2f}\nExit: {position['tp']:.2f}\nProfit: +${profit:.2f}\nBalance: ${balance:.2f}")
                        position = None
                elif position['side'] == 'SELL':
                    if price >= position['sl']:
                        loss = (position['sl'] - position['entry']) * position['size']
                        balance -= loss
                        state["total_trades"] += 1; state["losses"] += 1
                        tg(f"❌ *CLOSED - LOSS*\nPair: {SYMBOL}\nSHORT\nEntry: {position['entry']:.2f}\nExit: {price:.2f}\nLoss: -${loss:.2f}\nBalance: ${balance:.2f}")
                        position = None
                    elif price <= position['tp']:
                        profit = (position['entry'] - position['tp']) * position['size']
                        balance += profit
                        state["total_trades"] += 1; state["wins"] += 1
                        tg(f"✅ *CLOSED - WIN*\nPair: {SYMBOL}\nSHORT\nEntry: {position['entry']:.2f}\nExit: {position['tp']:.2f}\nProfit: +${profit:.2f}\nBalance: ${balance:.2f}")
                        position = None
            elif signal in ["BUY", "SELL"] and balance > 1:
                risk = balance * RISK_PCT
                if signal == "BUY":
                    entry = price; sl = gap_bottom; risk_unit = entry - sl
                    if risk_unit > 0:
                        size = risk / risk_unit
                        tp = entry + (risk_unit * 2)
                        position = {'side':'BUY','entry':round(entry,2),'sl':round(sl,2),'tp':round(tp,2),'size':size}
                        tg(f"🟢 *NEW PAPER TRADE*\n{SYMBOL} LONG\nEntry: {entry:.2f}\nSL: {sl:.2f}\nTP: {tp:.2f}")
                else:
                    entry = price; sl = gap_top; risk_unit = sl - entry
                    if risk_unit > 0:
                        size = risk / risk_unit
                        tp = entry - (risk_unit * 2)
                        position = {'side':'SELL','entry':round(entry,2),'sl':round(sl,2),'tp':round(tp,2),'size':size}
                        tg(f"🔴 *NEW PAPER TRADE*\n{SYMBOL} SHORT\nEntry: {entry:.2f}\nSL: {sl:.2f}\nTP: {tp:.2f}")
            time.sleep(60)
        except Exception as e:
            log(f"Error: {e}")
            state["status"] = f"ERROR: {e}"
            time.sleep(60)

app = Flask(__name__)
HTML = """
<!DOCTYPE html><html><head><meta http-equiv="refresh" content="30"><title>FVG Bot Monitor</title>
<style>body{font-family:sans-serif;background:#0f1115;color:#fff;padding:20px} .card{background:#1a1d24;padding:15px;border-radius:12px;margin-bottom:12px} .green{color:#00ff88} .red{color:#ff4444} .big{font-size:28px;font-weight:bold} small{color:#aaa}</style>
</head><body>
<h2>🤖 FVG + EMA Bot Monitor</h2>
<div class="card"><div>Status: <b class="green">{{s.status}}</b> | Last Update: {{s.last_update}}<br><small>Auto refreshes every 30s</small></div></div>
<div class="card"><div>Paper Balance</div><div class="big">${{s.balance}}</div><div>Start: $10 | Trades: {{s.total_trades}} | Wins: <span class="green">{{s.wins}}</span> | Losses: <span class="red">{{s.losses}}</span></div></div>
<div class="card"><div>BTC/USDT: <b>${{s.price}}</b> | EMA50: ${{s.ema50}} | EMA200: ${{s.ema200}} | Last Signal: {{s.last_signal}}</div></div>
<div class="card"><div>Open Position</div><pre>{{s.position}}</pre></div>
<div class="card"><div>Logs</div>{% for l in s.logs %}<div><small>{{l}}</small></div>{% endfor %}</div>
</body></html>
"""
@app.route("/")
def home():
    return render_template_string(HTML, s=state)
@app.route("/health")
def health():
    return jsonify({"status": state["status"], "balance": state["balance"], "last_update": state["last_update"]})
@app.route("/api")
def api():
    return jsonify(state)

threading.Thread(target=bot_loop, daemon=True).start()
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
