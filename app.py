import os
import json
import time
import hmac
import hashlib
import logging
import requests
from flask import Flask, request, jsonify

# -----------------------------
# تنظیمات اولیه
# -----------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# دریافت اطلاعات حساس از متغیرهای محیطی (در Render تنظیم می‌کنی)
API_KEY = os.environ.get("COINEX_API_KEY")
API_SECRET = os.environ.get("COINEX_API_SECRET").encode()
SIGNAL_PASSWORD = os.environ.get("SIGNAL_PASS")  # رمز اختصاصی برای سیگنال‌ها

BASE_URL = "https://api.coinex.com/v2/futures/order/put_limit"

# -----------------------------
# توابع کمکی
# -----------------------------

def sign_request(params):
    """ایجاد امضا برای درخواست‌های CoinEx"""
    sorted_params = sorted(params.items())
    query = '&'.join([f"{k}={v}" for k, v in sorted_params])
    signature = hmac.new(API_SECRET, query.encode(), hashlib.sha256).hexdigest()
    return signature

def send_order(symbol, side, order_type, quantity, price):
    """ارسال سفارش به CoinEx"""
    timestamp = int(time.time() * 1000)
    client_id = f"pl{timestamp}"

    params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": quantity,
        "price": price,
        "newClientOrderId": client_id,
        "timestamp": timestamp,
    }

    signature = sign_request(params)
    headers = {
        "X-COINEX-KEY": API_KEY,
        "Content-Type": "application/json",
    }

    payload = {**params, "signature": signature}

    logging.info(f"📤 ارسال سفارش: {payload}")

    response = requests.post(BASE_URL, headers=headers, json=payload)
    logging.info(f"📥 پاسخ CoinEx: {response.text}")

    return response.json()

# -----------------------------
# مسیر وبهوک
# -----------------------------
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()

    # بررسی رمز امنیتی
    password = data.get("password")
    if password != SIGNAL_PASSWORD:
        logging.warning("❌ رمز سیگنال نادرست است!")
        return jsonify({"error": "Invalid signal password"}), 403

    try:
        symbol = data["symbol"]
        side = data["side"]
        order_type = data["type"]
        quantity = data["quantity"]
        price = data["price"]

        result = send_order(symbol, side, order_type, quantity, price)
        return jsonify(result)
    except Exception as e:
        logging.error(f"❌ خطا در پردازش سیگنال: {e}")
        return jsonify({"error": str(e)}), 500

# ------------------ روت تست ------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "running", "time": int(time.time())})
    
# ------------------ اجرای محلی ------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

