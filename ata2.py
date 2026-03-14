from flask import Flask, request
import requests
import os
import hmac
import hashlib
import time
import json
import base64
from datetime import datetime
import threading

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
BITGET_API_KEY = os.environ.get("BITGET_API_KEY")
BITGET_SECRET_KEY = os.environ.get("BITGET_SECRET_KEY")
BITGET_PASSPHRASE = os.environ.get("BITGET_PASSPHRASE")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Bot State
bot_active = True
trade_history = []
daily_pnl = 0.0
total_capital = 2770.4992
last_analysis_time = None
analysis_count = 0

def send_telegram(message, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        requests.post(url, data=data, timeout=10)
    except:
        pass

def sign_request(timestamp, method, path, body=""):
    message = str(timestamp) + method + path + body
    sig_bytes = hmac.new(BITGET_SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(sig_bytes).decode()

def bitget_request(method, path, params=None, body=None):
    try:
        timestamp = str(int(time.time() * 1000))
        body_str = json.dumps(body) if body else ""
        if params:
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            sign_path = path + "?" + query_string
        else:
            sign_path = path
        signature = sign_request(timestamp, method, sign_path, body_str)
        base_url = "https://api.bitget.com"
        headers = {
            "ACCESS-KEY": BITGET_API_KEY,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": BITGET_PASSPHRASE,
            "Content-Type": "application/json",
            "x-simulated-trading": "1"
        }
        url = base_url + sign_path
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        else:
            response = requests.post(url, headers=headers, data=body_str, timeout=10)
        return response.json()
    except Exception as e:
        return {"code": "error", "msg": str(e)}

def get_candles(granularity, limit=100):
    try:
        params = {
            "symbol": "SBTCSUSDT",
            "productType": "SUSDT-FUTURES",
            "granularity": granularity,
            "limit": str(limit)
        }
        result = bitget_request("GET", "/api/v2/mix/market/candles", params=params)
        if result.get("code") == "00000":
            candles = result.get("data", [])
            return [{
                "time": c[0],
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5])
            } for c in candles]
        return []
    except:
        return []

def get_current_position():
    try:
        params = {
            "symbol": "SBTCSUSDT",
            "productType": "SUSDT-FUTURES",
            "marginCoin": "SUSDT"
        }
        result = bitget_request("GET", "/api/v2/mix/position/single-position", params=params)
        if result.get("code") == "00000" and result.get("data"):
            data = result["data"]
            if isinstance(data, dict):
                positions = [data]
            elif isinstance(data, list):
                positions = data
            else:
                return None, None, None, None
            for pos in positions:
                if float(pos.get("total", "0")) > 0:
                    return (
                        pos.get("holdSide"),
                        pos.get("openPriceAvg"),
                        pos.get("unrealizedPL"),
                        pos.get("total")
                    )
        return None, None, None, None
    except:
        return None, None, None, None

def get_account_balance():
    try:
        params = {
            "productType": "SUSDT-FUTURES",
            "marginCoin": "SUSDT"
        }
        result = bitget_request("GET", "/api/v2/mix/account/account", params=params)
        if result.get("code") == "00000":
            data = result.get("data", {})
            return float(data.get("usdtEquity", total_capital))
        return total_capital
    except:
        return total_capital

def get_btc_price():
    try:
        params = {"symbol": "SBTCSUSDT", "productType": "SUSDT-FUTURES"}
        result = bitget_request("GET", "/api/v2/mix/market/ticker", params=params)
        return float(result["data"][0]["lastPr"])
    except:
        return 70000.0

def set_leverage_bitget(leverage):
    bitget_request("POST", "/api/v2/mix/account/set-leverage", body={
        "symbol": "SBTCSUSDT",
        "productType": "SUSDT-FUTURES",
        "marginCoin": "SUSDT",
        "leverage": str(leverage)
    })

def open_order(side, size_usdt, leverage):
    try:
        set_leverage_bitget(leverage)
        price = get_btc_price()
        btc_size = round((size_usdt * leverage) / price, 4)
        result = bitget_request("POST", "/api/v2/mix/order/place-order", body={
            "symbol": "SBTCSUSDT",
            "productType": "SUSDT-FUTURES",
            "marginMode": "crossed",
            "marginCoin": "SUSDT",
            "size": str(btc_size),
            "side": side,
            "orderType": "market"
        })
        return result
    except Exception as e:
        return {"code": "error", "msg": str(e)}

def close_order(hold_side, size):
    try:
        close_side = "sell" if hold_side == "long" else "buy"
        return bitget_request("POST", "/api/v2/mix/order/place-order", body={
            "symbol": "SBTCSUSDT",
            "productType": "SUSDT-FUTURES",
            "marginMode": "crossed",
            "marginCoin": "SUSDT",
            "size": str(size),
            "side": close_side,
            "orderType": "market"
        })
    except:
        return None

def ask_claude(candles_5m, candles_15m, candles_1h, candles_4h, candles_1d, position, balance):
    try:
        def summarize(candles, n=30):
            c = candles[-n:]
            lines = []
            for x in c:
                lines.append(f"O:{x['open']:.0f} H:{x['high']:.0f} L:{x['low']:.0f} C:{x['close']:.0f} V:{x['volume']:.1f}")
            return "\n".join(lines)

        pos_text = "Keine offene Position"
        if position[0]:
            pos_text = f"{position[0].upper()} | Einstieg: ${position[1]} | PnL: {position[2]} SUSDT"

        recent_trades = ""
        if trade_history:
            recent_trades = "\n".join([f"- {t}" for t in trade_history[-5:]])

        prompt = f"""Du bist ATA3, eine hochentwickelte autonome Bitcoin Trading KI.

KONTOSTAND: {balance:.2f} SUSDT
AKTUELLE POSITION: {pos_text}
LETZTE TRADES: {recent_trades if recent_trades else 'Keine'}

MARKTDATEN SBTCUSDT:

5M Kerzen (letzte 30):
{summarize(candles_5m)}

15M Kerzen (letzte 30):
{summarize(candles_15m)}

1H Kerzen (letzte 30):
{summarize(candles_1h)}

4H Kerzen (letzte 30):
{summarize(candles_4h)}

1D Kerzen (letzte 30):
{summarize(candles_1d)}

DEINE AUFGABE:
1. Analysiere alle Timeframes auf Trends, Momentum, Support/Resistance, Volumen
2. Entscheide ob ein gutes Trading Setup vorhanden ist
3. Falls ja: definiere Einsatz und Hebel basierend auf Risiko
4. Ziel: Profit maximieren, Liquidation IMMER vermeiden
5. Halte Positionen nicht zu lange

WICHTIGE REGELN:
- Nur traden wenn Konfidenz >= 70%
- Hebel maximal 20x bei hoher Konfidenz, sonst weniger
- Einsatz maximal 10% des Kapitals pro Trade
- Bei offener Position: entscheide ob halten, schließen oder nichts tun
- Lerne aus vergangenen Trades

Antworte NUR in diesem JSON Format ohne Markdown:
{{
  "action": "BUY" oder "SELL" oder "CLOSE" oder "HOLD",
  "confidence": 0-100,
  "leverage": 1-20,
  "margin_usdt": Betrag in USDT,
  "reason": "Begründung auf Deutsch in 2-3 Sätzen",
  "trend_short": "bullish/bearish/neutral",
  "trend_medium": "bullish/bearish/neutral",
  "trend_long": "bullish/bearish/neutral",
  "risk_level": "low/medium/high",
  "expected_duration": "Minuten/Stunden"
}}"""

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        result = response.json()
        text = result["content"][0]["text"].strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        return None

def run_analysis():
    global last_analysis_time, analysis_count, daily_pnl, trade_history

    if not bot_active:
        return

    analysis_count += 1
    last_analysis_time = datetime.now().strftime("%H:%M:%S")

    # Kerzen von mehreren Timeframes holen
    candles_5m = get_candles("5m", 100)
    candles_15m = get_candles("15m", 100)
    candles_1h = get_candles("1H", 100)
    candles_4h = get_candles("4H", 100)
    candles_1d = get_candles("1D", 50)

    if not candles_1h:
        return

    hold_side, avg_price, unrealized_pnl, pos_size = get_current_position()
    balance = get_account_balance()
    position = (hold_side, avg_price, unrealized_pnl)

    analysis = ask_claude(candles_5m, candles_15m, candles_1h, candles_4h, candles_1d, position, balance)

    if not analysis:
        return

    action = analysis.get("action", "HOLD")
    confidence = analysis.get("confidence", 0)
    leverage = analysis.get("leverage", 5)
    margin = analysis.get("margin_usdt", 50)
    reason = analysis.get("reason", "")
    trend_short = analysis.get("trend_short", "")
    trend_medium = analysis.get("trend_medium", "")
    trend_long = analysis.get("trend_long", "")
    risk_level = analysis.get("risk_level", "medium")
    duration = analysis.get("expected_duration", "unbekannt")
    now = datetime.now().strftime("%H:%M")

    # Sicherheits Check
    max_margin = balance * 0.10
    margin = min(margin, max_margin)
    leverage = min(leverage, 20)

    if action == "BUY" and confidence >= 70:
        if hold_side == "short":
            pnl = float(unrealized_pnl) if unrealized_pnl else 0
            close_order("short", pos_size)
            daily_pnl += pnl
            trade_history.append(f"SHORT geschlossen | PnL: {round(pnl, 2)}$ | {now}")
            send_telegram(
                f"🔄 *Short geschlossen!*\n"
                f"💵 PnL: {'+' if pnl >= 0 else ''}{round(pnl, 2)}$"
            )
            time.sleep(1)

        if hold_side != "long":
            result = open_order("buy", margin, leverage)
            if result.get("code") == "00000":
                trade_history.append(f"LONG eröffnet | Margin: {margin}$ | Hebel: {leverage}x | {now}")
                send_telegram(
                    f"🟢 *ATA3 – LONG eröffnet!*\n\n"
                    f"🤖 Konfidenz: *{confidence}%*\n"
                    f"💰 Margin: {round(margin, 2)} USDT\n"
                    f"⚡ Hebel: {leverage}x\n"
                    f"📊 Positionswert: ~{round(margin * leverage, 0)} USDT\n"
                    f"⚠️ Risiko: {risk_level}\n"
                    f"⏱ Erwartete Dauer: {duration}\n\n"
                    f"📈 Trends: {trend_short} | {trend_medium} | {trend_long}\n\n"
                    f"📝 *Begründung:*\n{reason}\n\n"
                    f"⏰ {now} Uhr"
                )

    elif action == "SELL" and confidence >= 70:
        if hold_side == "long":
            pnl = float(unrealized_pnl) if unrealized_pnl else 0
            close_order("long", pos_size)
            daily_pnl += pnl
            trade_history.append(f"LONG geschlossen | PnL: {round(pnl, 2)}$ | {now}")
            send_telegram(
                f"🔄 *Long geschlossen!*\n"
                f"💵 PnL: {'+' if pnl >= 0 else ''}{round(pnl, 2)}$"
            )
            time.sleep(1)

        if hold_side != "short":
            result = open_order("sell", margin, leverage)
            if result.get("code") == "00000":
                trade_history.append(f"SHORT eröffnet | Margin: {margin}$ | Hebel: {leverage}x | {now}")
                send_telegram(
                    f"🔴 *ATA3 – SHORT eröffnet!*\n\n"
                    f"🤖 Konfidenz: *{confidence}%*\n"
                    f"💰 Margin: {round(margin, 2)} USDT\n"
                    f"⚡ Hebel: {leverage}x\n"
                    f"📊 Positionswert: ~{round(margin * leverage, 0)} USDT\n"
                    f"⚠️ Risiko: {risk_level}\n"
                    f"⏱ Erwartete Dauer: {duration}\n\n"
                    f"📉 Trends: {trend_short} | {trend_medium} | {trend_long}\n\n"
                    f"📝 *Begründung:*\n{reason}\n\n"
                    f"⏰ {now} Uhr"
                )

    elif action == "CLOSE" and hold_side:
        pnl = float(unrealized_pnl) if unrealized_pnl else 0
        close_order(hold_side, pos_size)
        daily_pnl += pnl
        trade_history.append(f"{hold_side.upper()} geschlossen | PnL: {round(pnl, 2)}$ | {now}")
        send_telegram(
            f"🔄 *Position geschlossen!*\n\n"
            f"💵 PnL: {'+' if pnl >= 0 else ''}{round(pnl, 2)}$\n"
            f"📝 *Grund:*\n{reason}\n\n"
            f"⏰ {now} Uhr"
        )

def analysis_loop():
    while True:
        try:
            run_analysis()
        except:
            pass
        time.sleep(300)  # Alle 5 Minuten

def send_control_panel():
    hold_side, avg_price, unrealized_pnl, size = get_current_position()
    balance = get_account_balance()

    if hold_side:
        pos_emoji = "🟢" if hold_side == "long" else "🔴"
        pnl = float(unrealized_pnl) if unrealized_pnl else 0
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        pos_text = (
            f"{pos_emoji} Position: *{hold_side.upper()}*\n"
            f"💵 Einstieg: ${avg_price}\n"
            f"{pnl_emoji} PnL: {'+' if pnl >= 0 else ''}{round(pnl, 2)}$"
        )
    else:
        pos_text = "⚪ Position: *Keine*"

    status = "🟢 AN" if bot_active else "🔴 AUS"

    keyboard = {"inline_keyboard": [
        [{"text": "🔍 Jetzt analysieren", "callback_data": "analyze"},
         {"text": "📊 Status", "callback_data": "status"}],
        [{"text": "📈 Trade Historie", "callback_data": "history"},
         {"text": f"🤖 Bot: {status}", "callback_data": "toggle"}],
        [{"text": "🛑 Position schließen", "callback_data": "close_pos"}]
    ]}

    send_telegram(
        f"🤖 *ATA3 – KI Trading Bot*\n\n"
        f"{pos_text}\n\n"
        f"💰 Kontostand: *{round(balance, 2)} SUSDT*\n"
        f"📊 Tages PnL: {'+' if daily_pnl >= 0 else ''}{round(daily_pnl, 2)}$\n"
        f"🔄 Analysen heute: {analysis_count}\n"
        f"⏰ Letzte Analyse: {last_analysis_time or 'Noch keine'}\n"
        f"🤖 Bot Status: {status}",
        reply_markup=keyboard
    )

@app.route('/telegram', methods=['POST'])
def telegram_update():
    global bot_active
    data = request.json

    message = data.get("message", {})
    text = message.get("text", "")

    if text == "/start":
        send_control_panel()
        return "OK", 200

    if text and text.startswith("/chat "):
        user_message = text.replace("/chat ", "").strip()
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 500,
                    "system": "Du bist ATA3, eine autonome Bitcoin Trading KI. Antworte kurz und präzise auf Deutsch. Du hast Zugriff auf Bitget Simulator und tradest BTC autonom.",
                    "messages": [{"role": "user", "content": user_message}]
                },
                timeout=30
            )
            result = response.json()
            reply = result["content"][0]["text"]
            send_telegram(f"🤖 *ATA3:*\n{reply}")
        except:
            send_telegram("❌ KI nicht erreichbar!")
        return "OK", 200

    callback = data.get("callback_query", {})
    callback_data = callback.get("data", "")

    if callback_data == "analyze":
        send_telegram("🔍 *Analysiere Markt...*")
        threading.Thread(target=run_analysis).start()

    elif callback_data == "status":
        send_control_panel()

    elif callback_data == "toggle":
        bot_active = not bot_active
        send_telegram(f"🤖 Bot {'aktiviert 🟢' if bot_active else 'deaktiviert 🔴'}!")
        send_control_panel()

    elif callback_data == "close_pos":
        hold_side, avg_price, unrealized_pnl, pos_size = get_current_position()
        if hold_side:
            pnl = float(unrealized_pnl) if unrealized_pnl else 0
            close_order(hold_side, pos_size)
            send_telegram(f"🔄 *Position manuell geschlossen!*\n💵 PnL: {'+' if pnl >= 0 else ''}{round(pnl, 2)}$")
        else:
            send_telegram("⚪ Keine offene Position!")

    elif callback_data == "history":
        if trade_history:
            msg = "📈 *Trade Historie:*\n\n" + "\n".join([f"• {t}" for t in trade_history[-10:]])
        else:
            msg = "📈 *Trade Historie:*\n\nNoch keine Trades!"
        send_telegram(msg)

    return "OK", 200

@app.route('/analyze')
def analyze():
    threading.Thread(target=run_analysis).start()
    return "Analyse gestartet!", 200

@app.route('/')
def home():
    return "ATA3 KI Trading Bot laeuft! ✅"

# Analyse Loop starten
analysis_thread = threading.Thread(target=analysis_loop, daemon=True)
analysis_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
