from flask import Flask, request
import requests
import os

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    signal = data.get("signal", "").upper()
    price = data.get("price", "N/A")

    if signal == "BUY":
        send_telegram(f"🟢 *ATA 1 – BUY SIGNAL!*\n\n📊 BTCUSD\n💡 LONG eröffnen!\n💰 Preis: ${price}")
    elif signal == "SELL":
        send_telegram(f"🔴 *ATA 1 – SELL SIGNAL!*\n\n📊 BTCUSD\n💡 SHORT eröffnen!\n💰 Preis: ${price}")

    return "OK", 200

@app.route('/')
def home():
    return "ATA1 läuft! ✅"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
