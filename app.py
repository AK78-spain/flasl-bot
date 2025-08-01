import os
import time
import json
import hmac
import hashlib
import logging
import requests
from flask import Flask, request, jsonify

# ------------------ تنظیمات عمومی ------------------
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)  # برای لاگ‌ها در Render

API_KEY = os.getenv("COINEX_API_KEY")
API_SECRET = os.getenv("COINEX_API_SECRET")
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api.coinex.com/v2"

# نگهداری آخرین سیگنال برای جلوگیری از تکرار
last_signal = {"data": None, "time": 0}
signal_cooldown = 5  # ثانیه


# ------------------ تابع ارسال پیام تلگرام ------------------
def send_telegram(msg: str):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
        except Exception as e:
            logging.error(f"Telegram Error: {e}")


# ------------------ تابع ساخت امضا ------------------
def generate_signature(method: str, request_path: str, body: dict = None):
    timestamp = str(int(time.time() * 1000))
    body_str = ""
    if body:
        # JSON بدون فاصله و با ترتیب پایدار
        body_str = json.dumps(body, separators=(',', ':'))

    prepared_str = method.upper() + request_path + body_str + timestamp
    signature = hmac.new(
        API_SECRET.encode("latin-1"),
        prepared_str.encode("latin-1"),
        hashlib.sha256
    ).hexdigest().lower()

    return signature, timestamp


# ------------------ تابع ارسال درخواست امن ------------------
def coinex_request(method, endpoint, body=None):
    url = BASE_URL + endpoint
    signature, timestamp = generate_signature(method, endpoint, body)

    headers = {
        "X-COINEX-KEY": API_KEY,
        "X-COINEX-SIGN": signature,
        "X-COINEX-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

    try:
        if method.upper() == "POST":
            response = requests.post(url, headers=headers, json=body)
        else:
            response = requests.get(url, headers=headers, params=body)
        logging.info(f"CoinEx Response: {response.text}")
        return response.json()
    except Exception as e:
        logging.error(f"Request Error: {e}")
        return None


# ------------------ روت تست ------------------
@app.route("/")
def home():
    return "Bot is running!"


# ------------------ روت وبهوک ------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    global last_signal

    data = request.get_json()
    logging.info(f"Received Signal: {data}")

    # بررسی پسورد وبهوک
    if not data or data.get("passphrase") != WEBHOOK_PASSPHRASE:
        return jsonify({"status": "error", "msg": "Invalid passphrase"}), 401

    # جلوگیری از ثبت سفارش تکراری
    current_time = time.time()
    if last_signal["data"] == data and current_time - last_signal["time"] < signal_cooldown:
        logging.info("Duplicate signal ignored.")
        return jsonify({"status": "ignored"})

    last_signal = {"data": data, "time": current_time}

    # آماده‌سازی سفارش فیوچرز
    order_body = {
        "market": data["market"],
        "market_type": "FUTURES",
        "side": data["side"],
        "amount": data["amount"]
    }


logging.info(f"URL: {url}")                     #اضافه شده برای تست
logging.info(f"METHOD: {method}")
logging.info(f"BODY: {body}")

    # 1️⃣ ثبت سفارش
    order_resp = coinex_request("POST", "/v2/futures/order", order_body)

    # 2️⃣ تنظیم اهرم (اختیاری)
    if "leverage" in data:
        lev_body = {
            "market": data["market"],
            "market_type": "FUTURES",
            "margin_mode": "cross",
            "leverage": data["leverage"]
        }
        coinex_request("POST", "/v2/futures/adjust-position-leverage", lev_body)

    # 3️⃣ تنظیم حد ضرر و حد سود
    if "stop_loss" in data:
        sl_body = {
            "market": data["market"],
            "market_type": "FUTURES",
            "stop_loss_type": "mark_price",
            "stop_loss_price": str(data["stop_loss"])
        }
        coinex_request("POST", "/v2/futures/set-position-stop-loss", sl_body)

    if "take_profit_1" in data:
        tp_body = {
            "market": data["market"],
            "market_type": "FUTURES",
            "take_profit_type": "mark_price",
            "take_profit_price": str(data["take_profit_1"])
        }
        coinex_request("POST", "/v2/futures/set-position-take-profit", tp_body)

    # ارسال پیام تلگرام
    send_telegram(f"Signal executed: {data}")

    return jsonify({"status": "success", "data": order_resp})


# ------------------ اجرای برنامه ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
