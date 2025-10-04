import os
import json
import time
import hmac
import hashlib
import logging
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# تنظیمات API
API_KEY = "YOUR_API_KEY"
API_SECRET = "YOUR_API_SECRET"
BASE_URL = "https://api.coinex.com/v1"

# تنظیمات تلگرام
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

logging.basicConfig(level=logging.INFO)

def send_telegram_message(message: str):
    """ارسال پیام به تلگرام"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        requests.post(url, data=payload)
    except Exception as e:
        logging.error(f"Telegram error: {e}")

def sign_request(params, secret):
    """امضای درخواست برای کوینکس"""
    sorted_params = sorted(params.items())
    query = "&".join([f"{k}={v}" for k, v in sorted_params])
    to_sign = query + f"&secret_key={secret}"
    return hashlib.md5(to_sign.encode("utf-8")).hexdigest().upper()

def send_request(endpoint, params):
    """ارسال درخواست به کوینکس"""
    params["access_id"] = API_KEY
    params["tonce"] = int(time.time() * 1000)
    signature = sign_request(params, API_SECRET)
    headers = {"Authorization": signature, "Content-Type": "application/json"}
    url = f"{BASE_URL}{endpoint}"
    response = requests.post(url, headers=headers, data=json.dumps(params))
    return response.json()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()

    try:
        logging.info(f"Received signal: {data}")

        market = data.get("market")
        market_type = data.get("market_type", "FUTURES")
        side = data.get("side")  # buy یا sell
        order_type = data.get("type", "market")  # market یا limit
        price = data.get("price", None)
        amount = data.get("amount")

        # --- مرحله اول: بستن پوزیشن قبلی ---
        close_params = {
            "market": market,
            "market_type": market_type,
            "type": "market"  # همیشه مارکت برای بستن
        }
        close_resp = send_request("/futures/close-position", close_params)
        logging.info(f"Close position response: {close_resp}")
        send_telegram_message(f"⛔️ Closing old position {market} -> {close_resp}")

        # --- فاصله 1 ثانیه ---
        time.sleep(1)

        # --- مرحله دوم: ایجاد سفارش جدید ---
        order_params = {
            "market": market,
            "market_type": market_type,
            "side": side,
            "type": order_type,
            "amount": amount
        }

        if order_type == "limit" and price is not None:
            order_params["price"] = price

        order_resp = send_request("/futures/order", order_params)
        logging.info(f"New order response: {order_resp}")
        send_telegram_message(f"✅ New order placed: {market} {side} {amount} {order_type} {price if price else ''}")

        return jsonify({"status": "success", "order_response": order_resp})

    except Exception as e:
        logging.error(f"Error: {str(e)}")
        send_telegram_message(f"⚠️ Error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 400

if __name__ == "__main__":
    app.run(port=5000)
