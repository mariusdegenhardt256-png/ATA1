from flask import Flask, request
import requests
import os
import hmac
import hashlib
import time
import json
import base64
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
BITGET_API_KEY = os.environ.get("BITGET_API_KEY")
BITGET_SECRET_KEY = os.environ.get("BITGET_SECRET_KEY")
BITGET_PASSPHRASE = os.environ.get("BITGET_PASSPHRASE")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

leverage = 10
amount_usdt = 100
waiting_for = None
last_analysis = None
bot_active = True

def send_telegram(message, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, data=data)

def sign_request(timestamp, method, path, body=""):
    message = str(timestamp) + method + path + body
    sig_bytes = hmac.new(BITGET_SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
    signature = base64.b64encode(sig_bytes).decode()
    return signature

def bitget_request(method, path, params=None, body=None):
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
        response = requests.get(url, headers=headers)
    else:
        response = requests.post(url, headers=headers, data=body_str)
    return response.json()

def get_candles(granularity, limit=50):
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
            formatted = []
            for c in candles:
                formatted.append({
                    "time": c[0],
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5])
                })
            return formatted
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
                size = float(pos.get("total", "0"))
                if size > 0:
                    return (
                        pos.get("holdSide"),
                        pos.get("openPriceAvg"),
                        pos.get("unrealizedPL"),
                        pos.get("total")
                    )
        return None, None, None, None
    except:
        return None, None, None, None

def get_btc_size():
    try:
        params = {"symbol": "SBTCSUSDT", "productType": "SUSDT-FUTURES"}
        result = bitget_request("GET", "/api/v2/mix/market/ticker", params=params)
        price = float(result["data"][0]["lastPr"])
        size = (amount_usdt * leverage) / price
        return str(round(size, 4))
    except:
        return "0.0145"

def set_leverage_bitget():
    path = "/api/v2/mix/account/set-leverage"
    body = {
        "symbol": "SBTCSUSDT",
        "productType": "SUSDT-FUTURES",
        "marginCoin": "SUSDT",
        "leverage": str(leverage)
    }
    return bitget_request("POST", path, body=body)

def open_order(side):
    set_leverage_bitget()
    btc_size = get_btc_size()
    path = "/api/v2/mix/order/place-order"
    body = {
        "symbol": "SBTCSUSDT",
        "productType": "SUSDT-FUTURES",
        "marginMode": "crossed",
        "marginCoin": "SUSDT",
        "size": btc_size,
        "side": side,
        "orderType": "market"
    }
    return bitget_request("POST", path, body=body)

def close_order(hold_side, size):
    path = "/api/v2/mix/order/place-order"
    close_side = "sell" if hold_side == "long" else "buy"
    body = {
        "symbol": "SBTCSUSDT",
        "productType": "SUSDT-FUTURES",
        "marginMode": "crossed",
        "marginCoin": "SUSDT",
        "size": str(size),
        "side": close_side,
        "orderType": "market"
    }
    return bitget_request("POST", path, body=body)

def ask_claude(candles_1h, candles_3h, candles_1d, current_position):
    try:
        def format_candles(candles):
            return [f"O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']} V:{c['volume']}" for c in candles[-20:]]

        pos_text = f"{current_position[0].upper()} seit ${current_position[1]}, PnL: {current_position[2]}" if current_position[0] else "Keine Position"

        prompt = f"""Du bist eine professionelle Trading KI für Bitcoin Futures.

Aktuelle Position: {pos_text}

BTC/USDT Kerzen:

1H (letzte 20):
{chr(10).join(format_candles(candles_1h))}

3H (letzte 20):
{chr(10).join(format_candles(candles_3h))}

1D (letzte 20):
{chr(10).join(format_candles(candles_1d))}

Analysiere die Marktstruktur, Trends, Support/Resistance, Momentum und Volumen.

Antworte NUR in diesem JSON Format:
{{
  "decision": "BUY" oder "SELL" oder "HOLD",
  "confidence": 1-100,
  "reason": "kurze Begründung auf Deutsch",
  "trend_1h": "bullish/bearish/neutral",
  "trend_3h": "bullish/bearish/neutral", 
  "trend_1d": "bullish/bearish/neutral"
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
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        result = response.json()
        text = result["content"][0]["text"]
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        return None

def run_analysis():
    global last_analysis, bot_active
    if not bot_active:
        return

    candles_1h = get_candles("1H", 50)
    candles_3h = get_candles("3H", 50)
    candles_1d = get_candles("1D", 50)

    if not candles_1h or not candles_3h or not candles_1d:
        return

    hold_side, avg_price, unrealized_pnl, pos_size = get_current_position()
    current_position = (hold_side, avg_price, unrealized_pnl)

    analysis = ask_claude(candles_1h, candles_3h, candles_1d, current_position)
    if not analysis:
        return

    last_analysis = analysis
    decision = analysis.get("decision")
    confidence = analysis.get("confidence", 0)
    reason = analysis.get("reason", "")
    trend_1h = analysis.get("trend_1h", "")
    trend_3h = analysis.get("trend_3h", "")
    trend_1d = analysis.get("trend_1d", "")

    now = datetime.now().strftime("%H:%M")

    if decision == "BUY" and confidence >= 65:
        if hold_side == "short":
            close_order("short", pos_size)
            send_telegram(f"🔄 *Short geschlossen!*\n💵 Eintritt: ${avg_price}")
        if hold_side != "long":
            open_order("buy")
            send_telegram(
                f"🟢 *ATA3 – LONG geöffnet!*\n\n"
                f"🤖 KI Konfidenz: {confidence}%\n"
                f"📝 Grund: {reason}\n\n"
                f"📊 Trends:\n"
                f"1H: {trend_1h} | 3H: {trend_3h} | 1D: {trend_1d}\n\n"
                f"⏰ {now} Uhr"
            )

    elif decision == "SELL" and confidence >= 65:
        if hold_side == "long":
            close_order("long", pos_size)
            send_telegram(f"🔄 *Long geschlossen!*\n💵 Eintritt: ${avg_price}")
        if hold_side != "short":
            open_order("sell")
            send_telegram(
                f"🔴 *ATA3 – SHORT geöffnet!*\n\n"
                f"🤖 KI Konfidenz: {confidence}%\n"
                f"📝 Grund: {reason}\n\n"
                f"📊 Trends:\n"
                f"1H: {trend_1h} | 3H: {trend_3h} | 1D: {trend_1d}\n\n"
                f"⏰ {now} Uhr"
            )

    elif decision == "HOLD":
        pass

def send_control_panel():
    hold_side, avg_price, unrealized_pnl, size = get_current_position()
    if hold_side:
        pos_emoji = "🟢" if hold_side == "long" else "🔴"
        try:
            pnl = float(unrealized_pnl)
            pnl_emoji = "📈" if pnl >= 0 else "📉"
            pnl_text = f"\n{pnl_emoji} PnL: {'+' if pnl >= 0 else ''}{round(pnl, 2)}$"
        except:
            pnl_text = ""
        pos_text = hold_side.upper()
        entry_text = f"\n💵 Eintritt: ${avg_price}" if avg_price else ""
    else:
        pos_emoji = "⚪"
        pos_text = "Keine"
        pnl_text = ""
        entry_text = ""

    status_emoji = "🟢" if bot_active else "🔴"
    last = f"\n\n🤖 Letzte Analyse: {last_analysis['decision']} ({last_analysis['confidence']}%)\n📝 {last_analysis['reason']}" if last_analysis else ""

    keyboard = {"inline_keyboard": [
        [{"text": f"💰 Margin: {amount_usdt} USDT", "callback_data": "set_amount"},
         {"text": f"⚡ Hebel: {leverage}x", "callback_data": "set_leverage"}],
        [{"text": "🔍 Jetzt analysieren", "callback_data": "analyze"},
         {"text": "📊 Status", "callback_data": "status"}],
        [{"text": f"{status_emoji} Bot: {'AN' if bot_active else 'AUS'}", "callback_data": "toggle_bot"}]
    ]}
    send_telegram(
        f"🤖 *ATA3 KI Kontrollpanel*\n\n"
        f"{pos_emoji} Position: *{pos_text}*"
        f"{entry_text}"
        f"{pnl_text}\n\n"
        f"💰 Margin: {amount_usdt} USDT\n"
        f"⚡ Hebel: {leverage}x\n"
        f"📊 Positionswert: ~{amount_usdt * leverage} USDT\n"
        f"🎮 Modus: Demo"
        f"{last}",
        reply_markup=keyboard
    )

@app.route('/analyze', methods=['GET'])
def analyze():
    run_analysis()
    return "Analyse durchgeführt!", 200

@app.route('/telegram', methods=['POST'])
def telegram_update():
    global leverage, amount_usdt, waiting_for, bot_active
    data = request.json

    message = data.get("message", {})
    text = message.get("text", "")

    if text == "/start":
        send_control_panel()
        return "OK", 200

    if text and waiting_for == "amount":
        try:
            new_amount = int(text)
            if 10 <= new_amount <= 10000:
                amount_usdt = new_amount
                waiting_for = None
                send_telegram(f"✅ Margin auf *{new_amount} USDT* gesetzt!")
                send_control_panel()
            else:
                send_telegram("❌ Bitte zwischen 10 und 10000 USDT eingeben!")
        except:
            send_telegram("❌ Bitte eine Zahl eingeben!")
        return "OK", 200

    if text and waiting_for == "leverage":
        try:
            new_leverage = int(text)
            if 1 <= new_leverage <= 125:
                leverage = new_leverage
                waiting_for = None
                send_telegram(f"✅ Hebel auf *{new_leverage}x* gesetzt!")
                send_control_panel()
            else:
                send_telegram("❌ Bitte zwischen 1 und 125 eingeben!")
        except:
            send_telegram("❌ Bitte eine Zahl eingeben!")
        return "OK", 200

    if text and text.startswith("/chat"):
        user_message = text.replace("/chat", "").strip()
        if user_message:
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
                        "system": "Du bist ATA3, eine professionelle Bitcoin Trading KI. Antworte kurz und präzise auf Deutsch.",
                        "messages": [{"role": "user", "content": user_message}]
                    }
                )
                result = response.json()
                reply = result["content"][0]["text"]
                send_telegram(f"🤖 *ATA3:* {reply}")
            except:
                send_telegram("❌ KI Fehler!")
        return "OK", 200

    callback = data.get("callback_query", {})
    callback_data = callback.get("data", "")

    if callback_data == "analyze":
        send_telegram("🔍 Analysiere Markt...")
        run_analysis()
        send_control_panel()
    elif callback_data == "status":
        send_control_panel()
    elif callback_data == "set_amount":
        waiting_for = "amount"
        send_telegram("💰 Schreibe die neue Margin in USDT:\nz.B: *100*")
    elif callback_data == "set_leverage":
        waiting_for = "leverage"
        send_telegram("⚡ Schreibe den neuen Hebel:\nz.B: *25*")
    elif callback_data == "toggle_bot":
        bot_active = not bot_active
        status = "aktiviert 🟢" if bot_active else "deaktiviert 🔴"
        send_telegram(f"🤖 ATA3 {status}!")
        send_control_panel()

    return "OK", 200

@app.route('/')
def home():
    return "ATA3 KI laeuft! ✅"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
