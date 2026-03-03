from flask import Flask, request
import requests
import os
import hmac
import hashlib
import time
import json
import base64

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
BITGET_API_KEY = os.environ.get("BITGET_API_KEY")
BITGET_SECRET_KEY = os.environ.get("BITGET_SECRET_KEY")
BITGET_PASSPHRASE = os.environ.get("BITGET_PASSPHRASE")

leverage = 10
amount_btc = "0.001"
amount_usdt = 100
current_position = None
entry_price = None
waiting_for = None

def send_telegram(message, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, data=data)

def calculate_pnl(close_price):
    if entry_price is None:
        return 0, 0
    ep = float(entry_price)
    cp = float(close_price)
    if current_position == "long":
        pnl_pct = ((cp - ep) / ep) * 100 * leverage
        pnl_usd = (cp - ep) / ep * amount_usdt * leverage
    else:
        pnl_pct = ((ep - cp) / ep) * 100 * leverage
        pnl_usd = (ep - cp) / ep * amount_usdt * leverage
    return round(pnl_usd, 2), round(pnl_pct, 2)

def send_control_panel(current_price=None):
    pnl_text = ""
    pos_text = current_position.upper() if current_position else "Keine"
    pos_emoji = "🟢" if current_position == "long" else "🔴" if current_position == "short" else "⚪"
    if current_position and current_price:
        pnl_usd, pnl_pct = calculate_pnl(current_price)
        pnl_emoji = "📈" if pnl_usd >= 0 else "📉"
        pnl_text = f"\n{pnl_emoji} PnL: {'+' if pnl_usd >= 0 else ''}{pnl_usd}$ ({'+' if pnl_pct >= 0 else ''}{pnl_pct}%)"
    keyboard = {"inline_keyboard": [
        [{"text": f"💰 Einsatz: {amount_usdt} USDT", "callback_data": "set_amount"},
         {"text": f"⚡ Hebel: {leverage}x", "callback_data": "set_leverage"}],
        [{"text": "📊 Status", "callback_data": "status"},
         {"text": "🛑 Stop ATA2", "callback_data": "stop"}]
    ]}
    send_telegram(
        f"🤖 *ATA2 Kontrollpanel*\n\n"
        f"{pos_emoji} Position: *{pos_text}*"
        f"{pnl_text}\n\n"
        f"💰 Einsatz: {amount_usdt} USDT\n"
        f"⚡ Hebel: {leverage}x\n"
        f"🎮 Modus: Demo",
        reply_markup=keyboard
    )

def sign_request(timestamp, method, path, body=""):
    message = str(timestamp) + method + path + body
    sig_bytes = hmac.new(BITGET_SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
    signature = base64.b64encode(sig_bytes).decode()
    return signature

def bitget_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ""
    signature = sign_request(timestamp, method, path, body_str)
    base_url = "https://api.bitget.com"
    headers = {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": BITGET_PASSPHRASE,
        "Content-Type": "application/json",
        "x-simulated-trading": "1"
    }
    url = base_url + path
    if method == "GET":
        response = requests.get(url, headers=headers)
    else:
        response = requests.post(url, headers=headers, data=body_str)
    return response.json()

def set_leverage_bitget():
    path = "/api/v2/mix/account/set-leverage"
    body = {
        "symbol": "SBTCSUSDT",
        "productType": "SUSDT-FUTURES",
        "marginCoin": "SUSDT",
        "leverage": str(leverage)
    }
    return bitget_request("POST", path, body)

def open_order(side):
    set_leverage_bitget()
    path = "/api/v2/mix/order/place-order"
    body = {
        "symbol": "SBTCSUSDT",
        "productType": "SUSDT-FUTURES",
        "marginMode": "crossed",
        "marginCoin": "SUSDT",
        "size": amount_btc,
        "side": side,
        "tradeSide": "open",
        "orderType": "market"
    }
    return bitget_request("POST", path, body)

def close_order(side):
    path = "/api/v2/mix/order/place-order"
    body = {
        "symbol": "SBTCSUSDT",
        "productType": "SUSDT-FUTURES",
        "marginMode": "crossed",
        "marginCoin": "SUSDT",
        "size": amount_btc,
        "side": side,
        "tradeSide": "close",
        "orderType": "market"
    }
    return bitget_request("POST", path, body)

@app.route('/webhook', methods=['POST'])
def webhook():
    global current_position, entry_price
    data = request.json
    signal = data.get("signal", "").upper()
    price = data.get("price", "N/A")

    if signal == "BUY":
        if current_position == "short":
            pnl_usd, pnl_pct = calculate_pnl(price)
            close_order("buy")
            pnl_emoji = "📈" if pnl_usd >= 0 else "📉"
            send_telegram(
                f"🔄 *Short geschlossen!*\n\n"
                f"💵 Eintritt: ${entry_price}\n"
                f"💵 Austritt: ${price}\n"
                f"{pnl_emoji} PnL: {'+' if pnl_usd >= 0 else ''}{pnl_usd}$ ({'+' if pnl_pct >= 0 else ''}{pnl_pct}%)"
            )
        open_order("buy")
        current_position = "long"
        entry_price = price
        send_telegram(
            f"🟢 *ATA2 – LONG geöffnet!*\n\n"
            f"📊 SBTCSUSDT\n"
            f"💵 Ausführungspreis: ${price}\n"
            f"💰 Einsatz: {amount_usdt} USDT\n"
            f"⚡ Hebel: {leverage}x\n"
            f"🎮 Demo Modus"
        )

    elif signal == "SELL":
        if current_position == "long":
            pnl_usd, pnl_pct = calculate_pnl(price)
            close_order("sell")
            pnl_emoji = "📈" if pnl_usd >= 0 else "📉"
            send_telegram(
                f"🔄 *Long geschlossen!*\n\n"
                f"💵 Eintritt: ${entry_price}\n"
                f"💵 Austritt: ${price}\n"
                f"{pnl_emoji} PnL: {'+' if pnl_usd >= 0 else ''}{pnl_usd}$ ({'+' if pnl_pct >= 0 else ''}{pnl_pct}%)"
            )
        open_order("sell")
        current_position = "short"
        entry_price = price
        send_telegram(
            f"🔴 *ATA2 – SHORT geöffnet!*\n\n"
            f"📊 SBTCSUSDT\n"
            f"💵 Ausführungspreis: ${price}\n"
            f"💰 Einsatz: {amount_usdt} USDT\n"
            f"⚡ Hebel: {leverage}x\n"
            f"🎮 Demo Modus"
        )

    return "OK", 200

@app.route('/telegram', methods=['POST'])
def telegram_update():
    global leverage, amount_usdt, waiting_for
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
                send_telegram(f"✅ Einsatz auf *{new_amount} USDT* gesetzt!")
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

    callback = data.get("callback_query", {})
    callback_data = callback.get("data", "")

    if callback_data == "status":
        send_control_panel()
    elif callback_data == "set_amount":
        waiting_for = "amount"
        send_telegram("💰 Schreibe den neuen Einsatz in USDT:\nz.B: *100*")
    elif callback_data == "set_leverage":
        waiting_for = "leverage"
        send_telegram("⚡ Schreibe den neuen Hebel:\nz.B: *25*")
    elif callback_data == "stop":
        send_telegram("🛑 *ATA2 gestoppt!*")

    return "OK", 200

@app.route('/panel')
def panel():
    send_control_panel()
    return "Panel gesendet!", 200

@app.route('/test-buy')
def test_buy():
    global current_position, entry_price
    result = open_order("buy")
    current_position = "long"
    entry_price = "65000"
    send_telegram(
        f"🟢 *ATA2 TEST – LONG geöffnet!*\n\n"
        f"📊 SBTCSUSDT\n"
        f"💵 Ausführungspreis: $65000\n"
        f"💰 Einsatz: {amount_usdt} USDT\n"
        f"⚡ Hebel: {leverage}x\n"
        f"🎮 Demo Modus\n"
        f"📡 Bitget: {str(result)}"
    )
    return "Test gesendet!", 200

@app.route('/')
def home():
    return "ATA2 laeuft! ✅"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
