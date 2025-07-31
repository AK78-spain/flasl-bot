import os
import hmac
import hashlib
import time
import json
import logging
from flask import Flask, request, abort
import requests

# =====================[ تنظیمات اولیه ]=====================
# تنظیم logging برای نمایش در Render
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# لود متغیرهای محیطی
API_KEY = os.getenv("COINEX_API_KEY")
API_SECRET = os.getenv("COINEX_API_SECRET").encode()  # برای HMAC
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE")

BASE_URL = "https://api.coinex.com/v2/futures"

# =====================[ توابع کمکی ]=====================
def coinex_signature(params: dict) -> str:
    """
    ساخت امضای HMAC-SHA256 برای احراز هویت CoinEx
    """
    query = "&".join([f"{k}={params[k]}" for k in sorted(params)])
    return hmac.new(API_SECRET, query.encode(), hashlib.sha256).hexdigest()


def send_coinex_request(endpoint: str, method="POST", data=None):
    """
    ارسال درخواست به API کوینکس
    """
    if data is None:
        data = {}

    data["access_id"] = API_KEY
    data["timestamp"] = int(time.time() * 1000)

    # امضا
    signature = coinex_signature(data)
    headers = {
        "Authorization": signature,
        "Content-Type": "application/json"
    }

    url = f"{BASE_URL}{endpoint}"
    logging.info(f"Sending request to: {url} | Data: {data}")

    response = requests.request(method, url, headers=headers, data=json.dumps(data))
    try:
        resp_json = response.json()
    except:
        resp_json = {"error": response.text}

    logging.info(f"Response: {resp_json}")
    return resp_json


def place_futures_order(signal: dict):
    """
    ثبت سفارش فیوچرز با TP و SL طبق سیگنال TradingView
    """

    market = signal["market"]
    side = signal["side"].lower()  # الان دقیقا buy یا sell می‌ماند
    order_type = signal["type"].lower() 

    payload = {
        "market": market,
        "market_type": "FUTURES",
        "side": side,
        "type": order_type,
        "amount": signal["amount"],
        "leverage": signal["leverage"],
    }

  # اگر سفارش limit باشد باید قیمت داشته باشد
    if order_type == "limit" and "entry" in signal:
        payload["price"] = signal["entry"]

    # حد سود و ضرر
    if "take_profit_1" in signal:
        payload["take_profit_price"] = signal["take_profit_1"]
        payload["take_profit_type"] = "latest_price"
    if "stop_loss" in signal:
        payload["stop_loss_price"] = signal["stop_loss"]
        payload["stop_loss_type"] = "mark_price"

    # ثبت سفارش
    return send_coinex_request("/order/put-order", method="POST", data=payload)


# =====================[ وب‌هوک TradingView ]=====================
@app.route("/webhook", methods=["POST"])
def webhook():
    """
    دریافت سیگنال از TradingView و اجرای معامله
    """
    data = request.json
    logging.info(f"Webhook received: {data}")

    # اعتبارسنجی پاس‌فریز
    if data.get("passphrase") != WEBHOOK_PASSPHRASE:
        logging.warning("Invalid passphrase!")
        return jsonify({"status": "error", "msg": "Invalid passphrase"}), 403

    # ثبت سفارش
    result = place_futures_order(data)
    return jsonify(result)

# روت ساده برای تست
@app.route('/')
def home():
    return "✅ Bot is running!"

# =====================[ اجرای سرور روی Render ]=====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
