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
amount_usdt = 100
waiting_for = None

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

def get_btc_size():
    try:
        params = {"symbol": "SBTCSUSDT", "productType": "SUSDT-FUTURES"}
        result = bitget_request("GET", "/api/v2/mix/market/ticker", params=params)
        price = float(result["data"][0]["lastPr"])
        size = (amount_usdt * leverage) / price
        return str(round(size, 4))
    except:
        return "0.0145"

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
                pos = data
            elif isinstance(data, list) and len(data) > 0:
                pos = data[0]
            else:
                return None, None, None, None
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

def get_all_positions():
    try:
        params = {"productType": "SUSDT-FUTURES", "marginCoin": "SUSDT"}
        result = bitget_request("GET", "/api/v2/mix/position/all-position", params=params)
        if result.get("code") == "00000" and result.get("data"):
            data = result["data"]
            if isinstance(data, dict):
                data = [data]
            positions = []
            for pos in data:
                size = float(pos.get("total", "0"))
                if size > 0:
                    positions.append(pos)
            return positions
        return []
    except:
        return []

def calculate_pnl(entry, close, hold_side):
    try:
        ep = float(entry)
        cp = float(close)
        if hold_side == "long":
            pnl_pct = ((cp - ep) / ep) * 100 * leverage
            pnl_usd = (cp - ep) / ep * amount_usdt * leverage
        else:
            pnl_pct = ((ep - cp) / ep) * 100 * leverage
            pnl_usd = (ep - cp) / ep * amount_usdt * leverage
        return round(pnl_usd, 2), round(pnl_pct, 2)
    except:
        return 0, 0

def send_status():
    positions = get_all_positions()
    if not positions:
        send_telegram("📊 *ATA2 Status*\n\n⚪ Keine offenen Positionen")
        return

    msg = "📊 *ATA2 Status – Offene Positionen*\n\n"
    total_pnl = 0

    for pos in positions:
        side = pos.get("holdSide", "").upper()
        pos_emoji = "🟢" if pos.get("holdSide") == "long" else "🔴"
        pnl = float(pos.get("unrealizedPL", "0"))
        total_pnl += pnl
        pnl_emoji = "📈" if pnl >= 0 else "📉"

        entry = float(pos.get("openPriceAvg", "0"))
        current = float(pos.get("markPrice", "0"))
        margin = float(pos.get("marginSize", "0"))
        lev = pos.get("leverage", "0")
        liq = float(pos.get("liquidationPrice", "0"))
        size = pos.get("total", "0")

        if entry > 0 and current > 0:
            pnl_pct = ((current - entry) / entry) * 100
            if pos.get("holdSide") == "short":
                pnl_pct = -pnl_pct
            pnl_pct = round(pnl_pct * float(lev), 2)
        else:
            pnl_pct = 0

        msg += (
            f"{pos_emoji} *{pos.get('symbol', 'SBTCSUSDT')} – {side}*\n"
            f"💵 Eintritt: ${round(entry, 2)}\n"
            f"💵 Aktuell: ${round(current, 2)}\n"
            f"💰 Margin: ${round(margin, 2)}\n"
            f"⚡ Hebel: {lev}x\n"
            f"📊 Größe: {size} BTC\n"
            f"🔥 Liquidation: ${round(liq, 2)}\n"
            f"{pnl_emoji} PnL: {'+' if pnl >= 0 else ''}{round(pnl, 2)}$ ({'+' if pnl_pct >= 0 else ''}{pnl_pct}%)\n\n"
        )

    total_emoji = "📈" if total_pnl >= 0 else "📉"
    msg += f"─────────────────\n{total_emoji} *Gesamt PnL: {'+' if total_pnl >= 0 else ''}{round(total_pnl, 2)}$*"
    send_telegram(msg)

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

    keyboard = {"inline_keyboard": [
        [{"text": f"💰 Margin: {amount_usdt} USDT", "callback_data": "set_amount"},
         {"text": f"⚡ Hebel: {leverage}x", "callback_data": "set_leverage"}],
        [{"text": "📊 Status", "callback_data": "status"},
         {"text": "🛑 Stop ATA2", "callback_data": "stop"}]
    ]}
    send_telegram(
        f"🤖 *ATA2 Kontrollpanel*\n\n"
        f"{pos_emoji} Position: *{pos_text}*"
        f"{entry_text}"
        f"{pnl_text}\n\n"
        f"💰 Margin: {amount_usdt} USDT\n"
        f"⚡ Hebel: {leverage}x\n"
        f"📊 Positionswert: ~{amount_usdt * leverage} USDT\n"
        f"🎮 Modus: Demo",
        reply_markup=keyboard
    )

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
        "tradeSide": "open",
        "orderType": "market"
    }
    return bitget_request("POST", path, body=body)

def close_order(side, size):
    path = "/api/v2/mix/order/place-order"
    body = {
        "symbol": "SBTCSUSDT",
        "productType": "SUSDT-FUTURES",
        "marginMode": "crossed",
        "marginCoin": "SUSDT",
        "size": str(size),
        "side": side,
        "tradeSide": "close",
        "orderType": "market"
    }
    return bitget_request("POST", path, body=body)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    signal = data.get("signal", "").upper()
    price = data.get("price", "N/A")

    hold_side, avg_price, unrealized_pnl, pos_size = get_current_position()

    if signal == "BUY":
        if hold_side == "short":
            pnl_usd, pnl_pct = calculate_pnl(avg_price, price, "short")
            close_order("buy", pos_size)
            pnl_emoji = "📈" if pnl_usd >= 0 else "📉"
            send_telegram(
                f"🔄 *Short geschlossen!*\n\n"
                f"💵 Eintritt: ${avg_price}\n"
                f"💵 Austritt: ${price}\n"
                f"{pnl_emoji} PnL: {'+' if pnl_usd >= 0 else ''}{pnl_usd}$ ({'+' if pnl_pct >= 0 else ''}{pnl_pct}%)"
            )
        open_order("buy")
        send_telegram(
            f"🟢 *ATA2 – LONG geöffnet!*\n\n"
            f"📊 SBTCSUSDT\n"
            f"💵 Ausführungspreis: ${price}\n"
            f"💰 Margin: {amount_usdt} USDT\n"
            f"⚡ Hebel: {leverage}x\n"
            f"📊 Positionswert: ~{amount_usdt * leverage} USDT\n"
            f"🎮 Demo Modus"
        )

    elif signal == "SELL":
        if hold_side == "long":
            pnl_usd, pnl_pct = calculate_pnl(avg_price, price, "long")
            close_order("sell", pos_size)
            pnl_emoji = "📈" if pnl_usd >= 0 else "📉"
            send_telegram(
                f"🔄 *Long geschlossen!*\n\n"
                f"💵 Eintritt: ${avg_price}\n"
                f"💵 Austritt: ${price}\n"
                f"{pnl_emoji} PnL: {'+' if pnl_usd >= 0 else ''}{pnl_usd}$ ({'+' if pnl_pct >= 0 else ''}{pnl_pct}%)"
            )
        open_order("sell")
        send_telegram(
            f"🔴 *ATA2 – SHORT geöffnet!*\n\n"
            f"📊 SBTCSUSDT\n"
            f"💵 Ausführungspreis: ${price}\n"
            f"💰 Margin: {amount_usdt} USDT\n"
            f"⚡ Hebel: {leverage}x\n"
            f"📊 Positionswert: ~{amount_usdt * leverage} USDT\n"
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
                send_telegram(f"✅ Margin auf *{new_amount} USDT* gesetzt!\n📊 Positionswert: ~{new_amount * leverage} USDT")
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
                send_telegram(f"✅ Hebel auf *{new_leverage}x* gesetzt!\n📊 Positionswert: ~{amount_usdt * new_leverage} USDT")
                send_control_panel()
            else:
                send_telegram("❌ Bitte zwischen 1 und 125 eingeben!")
        except:
            send_telegram("❌ Bitte eine Zahl eingeben!")
        return "OK", 200

    callback = data.get("callback_query", {})
    callback_data = callback.get("data", "")

    if callback_data == "status":
        send_status()
    elif callback_data == "set_amount":
        waiting_for = "amount"
        send_telegram("💰 Schreibe die neue Margin in USDT:\nz.B: *100*")
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
    result = open_order("buy")
    send_telegram(
        f"🟢 *ATA2 TEST – LONG geöffnet!*\n\n"
        f"📊 SBTCSUSDT\n"
        f"💵 Ausführungspreis: $aktuell\n"
        f"💰 Margin: {amount_usdt} USDT\n"
        f"⚡ Hebel: {leverage}x\n"
        f"📊 Positionswert: ~{amount_usdt * leverage} USDT\n"
        f"🎮 Demo Modus\n"
        f"📡 Bitget: {str(result)}"
    )
    return "Test gesendet!", 200

@app.route('/test-sell')
def test_sell():
    hold_side, avg_price, unrealized_pnl, pos_size = get_current_position()
    if hold_side == "long":
        pnl_usd, pnl_pct = calculate_pnl(avg_price, avg_price, "long")
        close_order("sell", pos_size)
        send_telegram(f"🔄 *Long geschlossen (Test)!*\n\n💵 Eintritt: ${avg_price}")
    result = open_order("sell")
    send_telegram(
        f"🔴 *ATA2 TEST – SHORT geöffnet!*\n\n"
        f"📊 SBTCSUSDT\n"
        f"💰 Margin: {amount_usdt} USDT\n"
        f"⚡ Hebel: {leverage}x\n"
        f"📊 Positionswert: ~{amount_usdt * leverage} USDT\n"
        f"🎮 Demo Modus\n"
        f"📡 Bitget: {str(result)}"
    )
    return "Test gesendet!", 200

@app.route('/')
def home():
    return "ATA2 laeuft! ✅"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
