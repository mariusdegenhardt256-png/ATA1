from flask import Flask, request
import requests
import os
import hmac
import hashlib
import time
import json

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
BITGET_API_KEY = os.environ.get("BITGET_API_KEY")
BITGET_SECRET_KEY = os.environ.get("BITGET_SECRET_KEY")
BITGET_PASSPHRASE = os.environ.get("BITGET_PASSPHRASE")

leverage = 10
amount_usdt = 100
demo_mode = True
current_position = None

def send_telegram(message, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, data=data)

def send_control_panel():
    keyboard = {"inline_keyboard": [
        [{"text": f"💰 Einsatz: {amount_usdt} USDT", "callback_data": "set_amount"},
         {"text": f"⚡ Hebel: {leverage}x", "callback_data": "set_leverage"}],
        [{"text": "📊 Status", "callback_data": "status"},
         {"text": "🛑 Stop ATA2", "callback_data": "stop"}]
    ]}
    send_telegram("🤖 *ATA2 Kontrollpanel*\n\nWähle eine Option:", reply_markup=keyboard)

def sign_request(timestamp, method, path, body=""):
    message = str(timestamp) + method + path + body
    signature = hmac.new(BITGET_SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()
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
        "paptrading": "1"
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
        "size": str(amount_usdt),
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
        "size": str(amount_usdt),
        "side": side,
        "tradeSide": "close",
        "orderType": "market"
    }
    return bitget_request("POST", path, body)

@app.route('/webhook', methods=['POST'])
def webhook():
    global current_position
    data = request.json
    signal = data.get("signal", "").upper()
    price = data.get("price", "N/A")

    if signal == "BUY":
        if current_position == "short":
            result = close_order("buy")
            send_telegram(f"🔄 *Short geschlossen!*\n💰 Preis: ${price}")
        result = open_order("buy")
        current_position = "long"
        send_telegram(
            f"🟢 *ATA2 – LONG geöffnet!*\n\n"
            f"📊 SBTCSUSDT\n"
            f"💰 Einsatz: {amount_usdt} USDT\n"
            f"⚡ Hebel: {leverage}x\n"
            f"💵 Preis: ${price}\n"
            f"🎮 Demo Modus"
        )

    elif signal == "SELL":
        if current_position == "long":
            result = close_order("sell")
            send_telegram(f"🔄 *Long geschlossen!*\n💰 Preis: ${price}")
        result = open_order("sell")
        current_position = "short"
        send_telegram(
            f"🔴 *ATA2 – SHORT geöffnet!*\n\n"
            f"📊 SBTCSUSDT\n"
            f"💰 Einsatz: {amount_usdt} USDT\n"
            f"⚡ Hebel: {leverage}x\n"
            f"💵 Preis: ${price}\n"
            f"🎮 Demo Modus"
        )

    return "OK", 200

@app.route('/telegram', methods=['POST'])
def telegram_update():
    global leverage, amount_usdt
    data = request.json
    callback = data.get("callback_query", {})
    callback_data = callback.get("data", "")

    if callback_data == "status":
        send_telegram(
            f"📊 *ATA2 Status*\n\n"
            f"Position: {current_position or 'Keine'}\n"
            f"Einsatz: {amount_usdt} USDT\n"
            f"Hebel: {leverage}x\n"
            f"Modus: Demo"
        )
    elif callback_data == "set_amount":
        send_telegram("💰 Schreibe den neuen Einsatz:\nz.B: *100*")
    elif callback_data == "set_leverage":
        send_telegram("⚡ Schreibe den neuen Hebel:\nz.B: *10*")
    elif callback_data == "stop":
        send_telegram("🛑 *ATA2 gestoppt!*")

    return "OK", 200

@app.route('/panel')
def panel():
    send_control_panel()
    return "Panel gesendet!", 200

@app.route('/')
def home():
    return "ATA2 läuft! ✅"

@app.route('/test-buy')
def test_buy():
    with app.test_request_context():
        data = {"signal": "BUY", "price": "65000"}
        global current_position
        price = "65000"
        if current_position == "short":
            send_telegram(f"🔄 *Short geschlossen!*\n💰 Preis: ${price}")
        result = open_order("buy")
        current_position = "long"
        send_telegram(
            f"🟢 *ATA2 TEST – LONG geöffnet!*\n\n"
            f"📊 SBTCSUSDT\n"
            f"💰 Einsatz: {amount_usdt} USDT\n"
            f"⚡ Hebel: {leverage}x\n"
            f"💵 Preis: ${price}\n"
            f"🎮 Demo Modus"
        )
    return "BUY Test gesendet!", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
