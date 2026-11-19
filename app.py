# FVG + EMA 15m BOT - WITH MONITOR - PAPER $10 - SMART TREND + REVERSAL
import ccxt, pandas as pd, requests, time, datetime, threading, os
from flask import Flask, jsonify, render_template_string

# ===== CONFIG - Use Render Env Vars =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "PASTE_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "PASTE_CHAT_ID_HERE")
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
TIMEFRAME = "15m"
HTF_TIMEFRAME = "1h"
PAPER_BALANCE = 10.0
RISK_PCT = 0.10
REVERSAL_RISK_PCT = 0.05  # NEW: Half risk for reversal - because e dey more risky

exchange = ccxt.binance({'enableRateLimit': True})

# ===== STATE FOR MONITOR =====
state = {
    "status": "starting",
    "balance": PAPER_BALANCE,
    "price": 0,
    "ema50": 0,
    "ema200": 0,
    "trend": "Checking...",
    "htf_price": 0,
    "htf_ema200": 0,
    "pending_reversal": "None",  # NEW: Show waiting reversal for monitor
    "position": None,
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "last_signal": "None",
    "last_update": "Never",
    "logs": []
}

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

def get_df(tf=TIMEFRAME, limit=250):
    ohlcv = exchange.fetch_ohlcv(SYMBOL, tf, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['t','open','high','low','close','vol'])
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    return df

def get_trend():
    try:
        htf = get_df(HTF_TIMEFRAME, limit=250)
        last = htf.iloc[-1]
        price_htf = float(last['close'])
        ema50_htf = float(last['ema50'])
        ema200_htf = float(last['ema200'])
        ema50_5ago = float(htf.iloc[-5]['ema50'])
        slope_up = ema50_htf > ema50_5ago
        slope_down = ema50_htf < ema50_5ago
        state["htf_price"] = round(price_htf, 2)
        state["htf_ema200"] = round(ema200_htf, 2)
        if price_htf > ema200_htf and price_htf > ema50_htf and slope_up:
            return "UPTREND"
        if price_htf < ema200_htf and price_htf < ema50_htf and slope_down:
            return "DOWNTREND"
        return "RANGE"
    except Exception as e:
        log(f"Trend error: {e}")
        return "RANGE"

def get_swing_levels(df):
    # Last 20 candles before the FVG zone - to find last Higher Low / Lower High
    # For UPTREND reversal: swing_low = lowest low of last 20 candles
    # For DOWNTREND reversal: swing_high = highest high of last 20 candles
    recent = df.iloc[-23:-3]  # 20 candles before last 3
    swing_low = float(recent['low'].min())
    swing_high = float(recent['high'].max())
    return swing_low, swing_high

def check_fvg(df, trend):
    # Returns: signal, gap_top, gap_bottom, price, fvg_type
    # fvg_type = "TREND" or "PENDING_REVERSAL"
    c1 = df.iloc[-4]
    c3 = df.iloc[-2]
    price = df.iloc[-1]['close']
    ema50 = df.iloc[-1]['ema50']

    if trend == "RANGE":
        return None, None, None, price, None

    # --- UPTREND ---
    if trend == "UPTREND":
        # 1. Normal trend trade: Bullish FVG
        if c1['high'] < c3['low']:
            if price > ema50:
                return "BUY", c3['low'], c1['high'], price, "TREND"
        # 2. Possible reversal: Bearish FVG - DON'T TRADE YET, WAIT FOR BOS
        if c1['low'] > c3['high']:
            return None, c1['low'], c3['high'], price, "PENDING_BEARISH"
        return None, None, None, price, None

    # --- DOWNTREND ---
    if trend == "DOWNTREND":
        # 1. Normal trend trade: Bearish FVG
        if c1['low'] > c3['high']:
            if price < ema50:
                return "SELL", c1['low'], c3['high'], price, "TREND"
        # 2. Possible reversal: Bullish FVG - WAIT FOR BOS
        if c1['high'] < c3['low']:
            return None, c3['low'], c1['high'], price, "PENDING_BULLISH"
        return None, None, None, price, None

    return None, None, None, price, None

def bot_loop():
    balance = PAPER_BALANCE
    position = None
    pending = None  # {'type': 'BEARISH'/'BULLISH', 'gap_top': x, 'gap_bottom': x, 'swing_low': x, 'swing_high': x, 'candles_waited': 0}
    log("Bot loop started - SMART TREND + REVERSAL ON")
    tg(f"🤖 *FVG BOT LIVE - SMART MODE*\nPair: {SYMBOL}\nPaper: ${balance}\nRule: Trend 10% | Reversal 5% + BOS Confirm\nMonitor: Check Render link")
    state["status"] = "RUNNING"

    while True:
        try:
            trend = get_trend()
            state["trend"] = trend

            df = get_df()
            signal, gap_top, gap_bottom, price = check_fvg(df, trend)[0:4]
            fvg_type = check_fvg(df, trend)[4]

            state["price"] = round(float(price), 2)
            state["ema50"] = round(float(df.iloc[-1]['ema50']), 2)
            state["ema200"] = round(float(df.iloc[-1]['ema200']), 2)
            state["balance"] = round(balance, 2)
            state["position"] = position

            # ===== PENDING REVERSAL LOGIC =====
            # If new opposite FVG appear, save am as pending
            if fvg_type == "PENDING_BEARISH" and trend == "UPTREND" and not position:
                swing_low, swing_high = get_swing_levels(df)
                # Only save if new, not same as before
                if not pending or pending['gap_top'] != gap_top:
                    pending = {'type': 'BEARISH', 'gap_top': float(gap_top), 'gap_bottom': float(gap_bottom), 'swing_low': swing_low, 'candles_waited': 0}
                    state["pending_reversal"] = f"BEARISH FVG Waiting - Must break below ${swing_low:.2f} to confirm reversal"
                    log(f"PENDING Bearish Reversal: Gap {gap_bottom:.2f}-{gap_top:.2f} | Need close below Swing Low {swing_low:.2f}")
                    tg(f"👀 *POSSIBLE REVERSAL SPOTTED*\n{SYMBOL} Bearish FVG inside UPTREND\nGap: {gap_bottom:.2f} - {gap_top:.2f}\nWaiting for Break Below: ${swing_low:.2f}\nBot NO go SHORT until e break am - if na pullback, e go ignore am")

            elif fvg_type == "PENDING_BULLISH" and trend == "DOWNTREND" and not position:
                swing_low, swing_high = get_swing_levels(df)
                if not pending or pending['gap_bottom'] != gap_bottom:
                    pending = {'type': 'BULLISH', 'gap_top': float(gap_top), 'gap_bottom': float(gap_bottom), 'swing_high': swing_high, 'candles_waited': 0}
                    state["pending_reversal"] = f"BULLISH FVG Waiting - Must break above ${swing_high:.2f} to confirm reversal"
                    log(f"PENDING Bullish Reversal: Gap {gap_bottom:.2f}-{gap_top:.2f} | Need close above Swing High {swing_high:.2f}")
                    tg(f"👀 *POSSIBLE REVERSAL SPOTTED*\n{SYMBOL} Bullish FVG inside DOWNTREND\nGap: {gap_bottom:.2f} - {gap_top:.2f}\nWaiting for Break Above: ${swing_high:.2f}\nBot NO go BUY until e break am")

            # Check if pending reversal don confirm - BOS
            reversal_signal = None
            reversal_entry = price
            if pending and not position:
                pending['candles_waited'] += 1
                # Cancel pending after 10 candles (10 x 15m = 2.5 hours) - e don expire
                if pending['candles_waited'] > 10:
                    log(f"Pending reversal expired - na pullback, ignore am")
                    state["pending_reversal"] = "None - Expired, na pullback"
                    pending = None
                elif pending['type'] == 'BEARISH' and price < pending['swing_low']:
                    # CONFIRMED: Price break below last Higher Low = Real Reversal
                    reversal_signal = "SELL"
                    log(f"REVERSAL CONFIRMED: Bearish BOS - Price {price:.2f} < Swing Low {pending['swing_low']:.2f}")
                    tg(f"🔄 *REVERSAL CONFIRMED*\n{SYMBOL} Price break below Swing Low\nNow SHORT with half risk 5%")
                    state["pending_reversal"] = "CONFIRMED - Entering Reversal"
                    pending = None
                elif pending['type'] == 'BULLISH' and price > pending['swing_high']:
                    reversal_signal = "BUY"
                    log(f"REVERSAL CONFIRMED: Bullish BOS - Price {price:.2f} > Swing High {pending['swing_high']:.2f}")
                    tg(f"🔄 *REVERSAL CONFIRMED*\n{SYMBOL} Price break above Swing High\nNow BUY with half risk 5%")
                    state["pending_reversal"] = "CONFIRMED - Entering Reversal"
                    pending = None
                else:
                    state["last_signal"] = signal or f"Waiting BOS - {pending['type']}"
            else:
                if not pending:
                    state["pending_reversal"] = "None"
                state["last_signal"] = signal or f"No FVG - {trend}"

            log(f"Price {price:.2f} | Trend {trend} | Sig {signal} | Rev {reversal_signal} | Bal ${balance:.2f} | Pos {position} | Pending {pending}")

            # ===== CHECK OPEN POSITION =====
            if position:
                if position['side'] == 'BUY':
                    if price <= position['sl']:
                        loss = (position['entry'] - position['sl']) * position['size']
                        balance -= loss
                        state["total_trades"] += 1; state["losses"] += 1
                        tg(f"❌ *CLOSED - LOSS*\nPair: {SYMBOL}\nLONG {'(REVERSAL)' if position.get('is_reversal') else ''}\nEntry: {position['entry']:.2f}\nExit: {price:.2f}\nLoss: -${loss:.2f}\nBalance: ${balance:.2f}")
                        position = None
                    elif price >= position['tp']:
                        profit = (position['tp'] - position['entry']) * position['size']
                        balance += profit
                        state["total_trades"] += 1; state["wins"] += 1
                        tg(f"✅ *CLOSED - WIN*\nPair: {SYMBOL}\nLONG {'(REVERSAL)' if position.get('is_reversal') else ''}\nEntry: {position['entry']:.2f}\nExit: {position['tp']:.2f}\nProfit: +${profit:.2f}\nBalance: ${balance:.2f}")
                        position = None
                elif position['side'] == 'SELL':
                    if price >= position['sl']:
                        loss = (position['sl'] - position['entry']) * position['size']
                        balance -= loss
                        state["total_trades"] += 1; state["losses"] += 1
                        tg(f"❌ *CLOSED - LOSS*\nPair: {SYMBOL}\nSHORT {'(REVERSAL)' if position.get('is_reversal') else ''}\nEntry: {position['entry']:.2f}\nExit: {price:.2f}\nLoss: -${loss:.2f}\nBalance: ${balance:.2f}")
                        position = None
                    elif price <= position['tp']:
                        profit = (position['entry'] - position['tp']) * position['size']
                        balance += profit
                        state["total_trades"] += 1; state["wins"] += 1
                        tg(f"✅ *CLOSED - WIN*\nPair: {SYMBOL}\nSHORT {'(REVERSAL)' if position.get('is_reversal') else ''}\nEntry: {position['entry']:.2f}\nExit: {position['tp']:.2f}\nProfit: +${profit:.2f}\nBalance: ${balance:.2f}")
                        position = None

            # ===== ENTER NEW TRADE =====
            elif balance > 1:
                # A. Normal Trend Trade - Full Risk 10%
                if signal in ["BUY", "SELL"]:
                    risk = balance * RISK_PCT
                    if signal == "BUY":
                        entry = price; sl = gap_bottom; risk_unit = entry - sl
                        if risk_unit > 0:
                            size = risk / risk_unit
                            tp = entry + (risk_unit * 2)
                            position = {'side':'BUY','entry':round(entry,2),'sl':round(sl,2),'tp':round(tp,2),'size':size,'is_reversal':False}
                            tg(f"🟢 *NEW PAPER TRADE - TREND*\n{SYMBOL} LONG - {trend}\nEntry: {entry:.2f}\nSL: {sl:.2f}\nTP: {tp:.2f}\nRisk: 10%")
                    else:
                        entry = price; sl = gap_top; risk_unit = sl - entry
                        if risk_unit > 0:
                            size = risk / risk_unit
                            tp = entry - (risk_unit * 2)
                            position = {'side':'SELL','entry':round(entry,2),'sl':round(sl,2),'tp':round(tp,2),'size':size,'is_reversal':False}
                            tg(f"🔴 *NEW PAPER TRADE - TREND*\n{SYMBOL} SHORT - {trend}\nEntry: {entry:.2f}\nSL: {sl:.2f}\nTP: {tp:.2f}\nRisk: 10%")
                # B. Reversal Trade - Half Risk 5% - Only after BOS
                elif reversal_signal in ["BUY", "SELL"]:
                    risk = balance * REVERSAL_RISK_PCT
                    if reversal_signal == "BUY":
                        entry = price
                        # SL below the swing low we just broke, or below FVG bottom
                        sl = entry - (entry * 0.003)  # 0.3% SL for reversal, tight
                        risk_unit = entry - sl
                        size = risk / risk_unit
                        tp = entry + (risk_unit * 2)
                        position = {'side':'BUY','entry':round(entry,2),'sl':round(sl,2),'tp':round(tp,2),'size':size,'is_reversal':True}
                        tg(f"🟢 *NEW PAPER TRADE - REVERSAL*\n{SYMBOL} LONG REVERSAL\nEntry: {entry:.2f}\nSL: {sl:.2f}\nTP: {tp:.2f}\nRisk: 5% (Half)")
                    else:
                        entry = price
                        sl = entry + (entry * 0.003)
                        risk_unit = sl - entry
                        size = risk / risk_unit
                        tp = entry - (risk_unit * 2)
                        position = {'side':'SELL','entry':round(entry,2),'sl':round(sl,2),'tp':round(tp,2),'size':size,'is_reversal':True}
                        tg(f"🔴 *NEW PAPER TRADE - REVERSAL*\n{SYMBOL} SHORT REVERSAL\nEntry: {entry:.2f}\nSL: {sl:.2f}\nTP: {tp:.2f}\nRisk: 5% (Half)")

            time.sleep(60)
        except Exception as e:
            log(f"Error: {e}")
            state["status"] = f"ERROR: {e}"
            time.sleep(60)

# ===== MONITOR WEB PAGE =====
app = Flask(__name__)

HTML = """
<!DOCTYPE html><html><head><meta http-equiv="refresh" content="30"><title>FVG Bot Monitor</title>
<style>body{font-family:sans-serif;background:#0f1115;color:#fff;padding:20px} .card{background:#1a1d24;padding:15px;border-radius:12px;margin-bottom:12px} .green{color:#00ff88} .red{color:#ff4444} .yellow{color:#ffcc00} .big{font-size:28px;font-weight:bold} small{color:#aaa}</style>
</head><body>
<h2>🤖 FVG + EMA Bot Monitor - SMART</h2>
<div class="card"><div>Status: <b class="green">{{s.status}}</b> | Last Update: {{s.last_update}}<br><small>Auto refreshes every 30s</small></div></div>
<div class="card"><div>Paper Balance</div><div class="big">${{s.balance}}</div><div>Start: $10 | Trades: {{s.total_trades}} | Wins: <span class="green">{{s.wins}}</span> | Losses: <span class="red">{{s.losses}}</span></div></div>
<div class="card"><div><b>TREND (1H): {{s.trend}}</b> | 1H Price: ${{s.htf_price}} | 1H EMA200: ${{s.htf_ema200}}</div><div>BTC/USDT 15m: <b>${{s.price}}</b> | EMA50: ${{s.ema50}} | EMA200: ${{s.ema200}} | Last Signal: {{s.last_signal}}</div><div class="yellow"><b>Pending Reversal:</b> {{s.pending_reversal}}</div></div>
<div class="card"><div>Open Position</div><pre>{{s.position}}</pre></div>
<div class="card"><div>Logs</div>{% for l in s.logs %}<div><small>{{l}}</small></div>{% endfor %}</div>
</body></html>
"""

@app.route("/")
def home():
    return render_template_string(HTML, s=state)

@app.route("/health")
def health():
    return jsonify({"status": state["status"], "balance": state["balance"], "trend": state["trend"], "pending": state["pending_reversal"], "last_update": state["last_update"]})

@app.route("/api")
def api():
    return jsonify(state)

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
