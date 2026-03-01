from flask import Flask, request
import requests
import os

app = Flask(__name__)

# Telegram
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Bitget Demo
BITGET_API_KEY = os.environ.get("BITGET_API_KEY")
BITGET_SECRET_KEY = os.environ.get("BITGET_SECRET_KEY")
BITGET_PASSPHRASE = os.environ.get("BITGET_PASSPHRASE")

# Standard Einstellungen
leverage = 10
amount_usdt = 100
demo_mode = True
current_position = None  # 'long' oder 'short'

def send_telegram(message, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        import json
        data["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, data=data)

def send_control_panel():
    keyboard = {
        "inline_keyboard": [
            [
                {"text": f"💰 Einsatz: {amount_usdt} USDT", "callback_data": "set_amount"},
                {"text": f"⚡ Hebel: {leverage}x", "callback_data": "set_leverage"}
            ],
            [
                {"text": "📊 Status", "callback_data": "status"},
                {"text": "🛑 Stop ATA2", "callback_data": "stop"}
            ]
        ]
    }
    send_telegram("🤖 *ATA2 Kontrollpanel*\n\nWähle eine Option:", reply_markup=keyboard)

@app.route('/webhook', methods=['POST'])
def webhook():
    global current_position, leverage, amount_usdt
    data = request.json
    signal = data.get("signal", "").upper()
    price = data.get("price", "N/A")

    if signal == "BUY":
        if current_position == "short":
            send_telegram(f"🔄 *ATA2 – Short geschlossen!*\n💰 Preis: ${price}")
        current_position = "long"
        send_telegram(
            f"🟢 *ATA2 – LONG geöffnet!*\n\n"
            f"📊 BTCUSDT\n"
            f"💰 Einsatz: {amount_usdt} USDT\n"
            f"⚡ Hebel: {leverage}x\n"
            f"💵 Preis: ${price}\n"
            f"🎮 Modus: {'Demo' if demo_mode else 'Live'}"
        )

    elif signal == "SELL":
        if current_position == "long":
            send_telegram(f"🔄 *ATA2 – Long geschlossen!*\n💰 Preis: ${price}")
        current_position = "short"
        send_telegram(
            f"🔴 *ATA2 – SHORT geöffnet!*\n\n"
            f"📊 BTCUSDT\n"
            f"💰 Einsatz: {amount_usdt} USDT\n"
            f"⚡ Hebel: {leverage}x\n"
            f"💵 Preis: ${price}\n"
            f"🎮 Modus: {'Demo' if demo_mode else 'Live'}"
        )

    return "OK", 200

@app.route('/telegram', methods=['POST'])
def telegram_update():
    global leverage, amount_usdt
    data = request.json
    callback = data.get("callback_query", {})
    callback_data = callback.get("data", "")

    if callback_data == "set_amount":
        send_telegram("💰 Schreibe den neuen Einsatz in USDT:\nz.B: 100")
    elif callback_data == "set_leverage":
        send_telegram("⚡ Schreibe den neuen Hebel:\nz.B: 10")
    elif callback_data == "status":
        send_telegram(
            f"📊 *ATA2 Status*\n\n"
            f"Position: {current_position or 'Keine'}\n"
            f"Einsatz: {amount_usdt} USDT\n"
            f"Hebel: {leverage}x\n"
            f"Modus: {'Demo' if demo_mode else 'Live'}"
        )
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
