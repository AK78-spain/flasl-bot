import os
import time
import json
import hmac
import hashlib
import logging
import requests
from flask import Flask, request, jsonify

# -----------------------------
# تنظیمات Flask و Logging
# -----------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -----------------------------
# محیط‌های حساس
# -----------------------------
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE")
COINEX_ACCESS_ID = os.getenv("COINEX_ACCESS_ID")
COINEX_SECRET_KEY = os.getenv("COINEX_SECRET_KEY")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api.coinex.com"
last_signal = {"key": None, "time": 0}

# -----------------------------
# توابع کمکی
# -----------------------------

def send_telegram(message: str):
    """ارسال پیام به تلگرام"""
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})

def coinex_request(method, path, body=None):
    """ارسال درخواست امضاشده به CoinEx"""
    ts = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ""
    sig_str = method.upper() + path + body_str + ts
    signature = hmac.new(COINEX_SECRET_KEY.encode(), sig_str.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-COINEX-KEY": COINEX_ACCESS_ID,
        "X-COINEX-SIGN": signature,
        "X-COINEX-TIMESTAMP": ts,
        "Content-Type": "application/json"
    }
    url = BASE_URL + path
    r = requests.request(method, url, headers=headers, json=body)
    return r.json()

def process_signal(data):
    """پردازش سیگنال دریافتی و ارسال سفارش به CoinEx"""
    market = data["market"]
    side = data["side"]
    order_type = data["type"]
    amount = str(data["amount"])
    leverage = data.get("leverage", 5)
    entry = str(data.get("entry"))
    tp1 = str(data.get("take_profit_1"))
    sl = str(data.get("stop_loss"))

    # 1️⃣ تنظیم لوریج
    res1 = coinex_request("POST", "/v2/futures/adjust-position-leverage", {
        "market": market,
        "market_type": "FUTURES",
        "margin_mode": "cross",
        "leverage": leverage
    })
    logging.info(f"Set leverage: {res1}")

    # 2️⃣ باز کردن پوزیشن
    res2 = coinex_request("PUT", "/v2/futures/order", {
        "market": market,
        "market_type": "FUTURES",
        "side": side,
        "type": order_type,
        "amount": amount
    })
    logging.info(f"Open order: {res2}")

    # 3️⃣ تنظیم Stop Loss
    if sl:
        res3 = coinex_request("POST", "/v2/futures/set-position-stop-loss", {
            "market": market,
            "market_type": "FUTURES",
            "stop_loss_type": "mark_price",
            "stop_loss_price": sl
        })
        logging.info(f"Set SL: {res3}")

    # 4️⃣ تنظیم Take Profit
    if tp1:
        res4 = coinex_request("POST", "/v2/futures/set-position-take-profit", {
            "market": market,
            "market_type": "FUTURES",
            "take_profit_type": "latest_price",
            "take_profit_price": tp1
        })
        logging.info(f"Set TP: {res4}")

    msg = f"✅ New {side.upper()} order {market}\nEntry:{entry}\nTP:{tp1} | SL:{sl}"
    send_telegram(msg)
    return True

# -----------------------------
# روت‌ها
# -----------------------------

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "I am alive"}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    # 1️⃣ بررسی Passphrase
    if not data or data.get("passphrase") != WEBHOOK_PASSPHRASE:
        logging.warning("Invalid or missing passphrase")
        return jsonify({"status": "error", "message": "Invalid passphrase"}), 403

    # 2️⃣ جلوگیری از سفارش تکراری
    signal_key = f"{data['market']}_{data['side']}"
    now = time.time()
    if last_signal["key"] == signal_key and (now - last_signal["time"]) < 30:
        logging.info("Duplicate signal ignored")
        return jsonify({"status": "ignored", "message": "Duplicate signal"}), 200

    last_signal["key"] = signal_key
    last_signal["time"] = now

    # 3️⃣ پردازش سیگنال
    try:
        process_signal(data)
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logging.error(f"Error processing signal: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# -----------------------------
# اجرای محلی (برای تست)
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
