import os
import json
import time
import hmac
import hashlib
import logging
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# تنظیمات لاگ
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 🔑 اطلاعات API توبیت (از داشبورد توبیت خودت بگیر)
API_KEY = "YOUR_API_KEY"
API_SECRET = "YOUR_SECRET_KEY"

BASE_URL = "https://api.toobit.com"

# 🧩 تابع ساخت امضا HMAC SHA256
def generate_signature(params: dict, secret_key: str):
    query_string = "&".join([f"{key}={params[key]}" for key in params])
    signature = hmac.new(secret_key.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    return signature

# 📤 تابع ارسال سفارش
def place_order(symbol, side, type_, quantity, price):
    timestamp = int(time.time() * 1000)

    # تبدیل symbol به فرمت توبیت
    if not symbol.endswith("-SWAP-USDT"):
        symbol = f"{symbol.replace('USDT', '')}-SWAP-USDT"

    # تبدیل side به فرمت درست
    side_map = {
        "BUY": "BUY_OPEN",
        "SELL": "SELL_OPEN"
    }
    side = side_map.get(side.upper(), side)

    new_client_id = f"order_{int(time.time() * 1000)}"

    data = {
        "symbol": symbol,
        "side": side,
        "type": type_,
        "quantity": quantity,
        "price": price,
        "newClientOrderId": new_client_id,
        "timestamp": timestamp
    }

    signature = generate_signature(data, API_SECRET)
    data["signature"] = signature

    headers = {
        "Content-Type": "application/json",
        "X-BB-APIKEY": API_KEY
    }

    url = f"{BASE_URL}/api/v1/futures/order"

    logging.info(f"Sending order: {json.dumps(data, indent=2)}")

    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        logging.info(f"Response: {response.status_code} - {response.text}")
        return response.json()
    except Exception as e:
        logging.error(f"Error placing order: {e}")
        return {"error": str(e)}

# 🪄 مسیر وبهوک برای دریافت سیگنال از تریدینگ‌ویو
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        logging.info(f"Received signal: {data}")

        symbol = data.get("symbol")
        side = data.get("side")
        type_ = data.get("type", "LIMIT")
        quantity = data.get("quantity")
        price = data.get("price")

        result = place_order(symbol, side, type_, quantity, price)
        return jsonify(result)

    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 400

# ------------------ روت تست ------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "running", "time": int(time.time())})
    
# ------------------ اجرای محلی ------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

