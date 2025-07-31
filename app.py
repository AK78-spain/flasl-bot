import os
import time
import hmac
import hashlib
import json
import logging
from flask import Flask, request, jsonify
import requests

# -------------------- تنظیمات اولیه --------------------
logging.basicConfig(level=logging.INFO)

API_KEY = os.getenv("COINEX_API_KEY")
API_SECRET = os.getenv("COINEX_API_SECRET")
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE", "123456")

BASE_URL = "https://api.coinex.com/v2/futures"

app = Flask(__name__)

# -------------------- تابع امضا --------------------
def sign_request(method, path, params=None):
    """
    ساخت امضا طبق CoinEx API v2
    """
    if params is None:
        params = {}

    # زمان یونیکس
    timestamp = str(int(time.time() * 1000))

    # مرتب سازی پارامترها برای امضا
    query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])

    payload = f"{method.upper()}|{path}|{query}|{timestamp}"

    signature = hmac.new(
        API_SECRET.encode("utf-8"), 
        payload.encode("utf-8"), 
        hashlib.sha256
    ).hexdigest()

    headers = {
        "X-COINEX-KEY": API_KEY,
        "X-COINEX-SIGN": signature,
        "X-COINEX-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

    return headers

# -------------------- ارسال درخواست به CoinEx --------------------
def send_coinex_request(endpoint, method="POST", data=None):
    url = f"{BASE_URL}{endpoint}"
    headers = sign_request(method, endpoint, data)
    
    if method.upper() == "POST":
        resp = requests.post(url, headers=headers, data=json.dumps(data))
    else:
        resp = requests.get(url, headers=headers, params=data)

    logging.info(f"CoinEx Response: {resp.text}")
    return resp.json()

# -------------------- ثبت سفارش فیوچرز --------------------
def place_futures_order(signal: dict):
    market = signal["market"]
    side = signal["side"].lower()            # buy یا sell
    order_type = signal["type"].lower()      # market یا limit یا ...

    payload = {
        "market": market,
        "market_type": "FUTURES",
        "side": side,
        "type": order_type,
        "amount": signal["amount"],
        "leverage": signal.get("leverage", 5),
    }

    # اگر سفارش limit باشد باید قیمت داشته باشد
    if order_type == "limit" and "entry" in signal:
        payload["price"] = signal["entry"]

    # اضافه کردن حد سود و ضرر
    if "take_profit_1" in signal:
        payload["take_profit_price"] = signal["take_profit_1"]
        payload["take_profit_type"] = "latest_price"
    if "stop_loss" in signal:
        payload["stop_loss_price"] = signal["stop_loss"]
        payload["stop_loss_type"] = "mark_price"

    logging.info(f"Placing futures order: {payload}")
    return send_coinex_request("/order/put-order", method="POST", data=payload)

# -------------------- وبهوک TradingView --------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    if not data or data.get("passphrase") != WEBHOOK_PASSPHRASE:
        logging.warning("Invalid webhook request or passphrase.")
        return jsonify({"code": "error", "msg": "invalid request"}), 403

    logging.info(f"Received TradingView signal: {data}")
    result = place_futures_order(data)
    return jsonify(result)

# روت ساده برای تست
@app.route('/')
def home():
    return "✅ Bot is running!"


# -------------------- اجرای Flask روی Render --------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"Starting server on port {port}...")
    app.run(host="0.0.0.0", port=port)
