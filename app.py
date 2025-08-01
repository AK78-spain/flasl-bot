import os
import time
import hmac
import hashlib
import logging
import requests
from flask import Flask, request, jsonify

# ------------------ تنظیمات عمومی ------------------
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE", "12345")
COINEX_API_KEY = os.getenv("COINEX_API_KEY", "")
COINEX_API_SECRET = os.getenv("COINEX_API_SECRET", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BASE_URL = "https://api.coinex.com/v2"

# برای جلوگیری از سیگنال تکراری
last_signal = {"key": None, "timestamp": 0}
COOLDOWN_SECONDS = 5

# ------------------ توابع کمکی ------------------
def send_telegram_message(text: str):
    """ارسال پیام به تلگرام"""
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text})

def generate_signature(method, path, body, timestamp):
    """ساخت امضای CoinEx"""
    prepared_str = method.upper() + path
    if body:
        prepared_str += body
    prepared_str += str(timestamp)
    signature = hmac.new(
        COINEX_API_SECRET.encode('latin-1'),
        msg=prepared_str.encode('latin-1'),
        digestmod=hashlib.sha256
    ).hexdigest().lower()
    return signature

def coinex_request(method, endpoint, data=None):
    """ارسال درخواست به CoinEx"""
    url = BASE_URL + endpoint
    timestamp = int(time.time() * 1000)
    body_str = "" if method.upper() == "GET" else ("" if not data else str(data).replace("'", '"'))

    headers = {
        "X-COINEX-KEY": COINEX_API_KEY,
        "X-COINEX-SIGN": generate_signature(method, endpoint, body_str, timestamp),
        "X-COINEX-TIMESTAMP": str(timestamp),
        "Content-Type": "application/json"
    }

    resp = requests.request(method, url, headers=headers, json=data)
    logging.info(f"CoinEx Response: {resp.text}")
    return resp.json()

# ------------------ روت‌ها ------------------

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "running"})

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    logging.info(f"Received Signal: {data}")

    # 1. بررسی رمز عبور
    if data.get("passphrase") != WEBHOOK_PASSPHRASE:
        logging.warning("Invalid passphrase received")
        return jsonify({"status": "error", "msg": "Invalid passphrase"}), 403

    # 2. جلوگیری از سیگنال تکراری
    global last_signal
    signal_key = f"{data.get('market')}-{data.get('side')}"
    now = time.time()
    if last_signal["key"] == signal_key and now - last_signal["timestamp"] < COOLDOWN_SECONDS:
        logging.info("Duplicate signal ignored")
        return jsonify({"status": "ignored", "msg": "Duplicate signal"})

    last_signal = {"key": signal_key, "timestamp": now}

    # 3. ثبت سفارش فیوچرز در CoinEx
    market = data.get("market")
    side = data.get("side")
    amount = data.get("amount")
    leverage = data.get("leverage", 1)

    # تنظیم اهرم
    coinex_request("POST", "/futures/adjust-position-leverage", {
        "market": market,
        "market_type": "FUTURES",
        "margin_mode": "cross",
        "leverage": leverage
    })

    # ثبت سفارش مارکت
    order_resp = coinex_request("POST", "/futures/order", {
        "market": market,
        "market_type": "FUTURES",
        "side": side,
        "type": "market",
        "amount": amount
    })

    # اگر حد ضرر یا سود داده شده بود، ثبت کنیم
    if data.get("stop_loss"):
        coinex_request("POST", "/futures/set-position-stop-loss", {
            "market": market,
            "market_type": "FUTURES",
            "stop_loss_type": "mark_price",
            "stop_loss_price": str(data.get("stop_loss"))
        })

    if data.get("take_profit_1"):
        coinex_request("POST", "/futures/set-position-take-profit", {
            "market": market,
            "market_type": "FUTURES",
            "take_profit_type": "mark_price",
            "take_profit_price": str(data.get("take_profit_1"))
        })

    # 4. ارسال پیام تلگرام
    send_telegram_message(f"🚀 Signal Executed\n{data}")

    return jsonify({"status": "success", "msg": "Order executed", "order_response": order_resp})

# ------------------ اجرای لوکال ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
