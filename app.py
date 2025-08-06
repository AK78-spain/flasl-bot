import os
import json
import time
import hmac
import hashlib
import logging
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ------------- تنظیمات محیطی -------------
COINEX_API_KEY = os.getenv("COINEX_API_KEY")
COINEX_SECRET = os.getenv("COINEX_API_SECRET")
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE") 
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ذخیره آخرین سیگنال‌ها برای جلوگیری از تکرار
last_signal = {}
duplicate_delay = 30  # ثانیه

# ------------------ توابع کمکی ------------------
def send_telegram(msg: str):
    """ارسال پیام به تلگرام"""
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
            logging.info("📨 پیام به تلگرام ارسال شد")
        except Exception as e:
            logging.error(f"❌ Telegram error: {e}")

def place_futures_order(signal: dict):
    url = "https://api.coinex.com/v2/futures/order"
    method = "POST"
    timestamp = int(time.time() * 1000)

    payload = {
        "market": signal["market"],
        "market_type": "FUTURES",
        "side": signal["side"],
        "type": "market",
        "amount": signal["amount"],
    }

    body_str = json.dumps(payload, separators=(',', ':'))
    request_path = "/v2/futures/order"
    sign_str = method + request_path + body_str + str(timestamp)

    signature = hmac.new(
        COINEX_SECRET.encode('latin-1'),
        sign_str.encode('latin-1'),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "X-COINEX-KEY": COINEX_API_KEY,
        "X-COINEX-SIGN": signature,
        "X-COINEX-TIMESTAMP": str(timestamp),
        "Content-Type": "application/json"
    }

    logging.info(f"📤 ارسال سفارش به کوینکس: {payload}")
    resp = requests.post(url, data=body_str, headers=headers)

    if resp.text.strip() == "":
        logging.error(f"❌ پاسخ خالی از CoinEx [{resp.status_code}]")
        return None

    try:
        data = resp.json()
        logging.info(f"✅ پاسخ سفارش: {data}")
        return data
    except Exception as e:
        logging.error(f"❌ خطای JSON: {e} | Raw: {resp.text}")
        return None

def set_stop_loss(signal: dict, stop_price: str):
    """تنظیم حد ضرر پوزیشن"""
    url = "https://api.coinex.com/v2/futures/set-position-stop-loss"
    method = "POST"
    timestamp = int(time.time() * 1000)

    payload = {
        "market": signal["market"],
        "market_type": "FUTURES",
        "stop_loss_type": "mark_price",
        "stop_loss_price": str(stop_price)
    }

    body_str = json.dumps(payload, separators=(',', ':'))
    request_path = "/v2/futures/set-position-stop-loss"
    sign_str = method + request_path + body_str + str(timestamp)

    signature = hmac.new(
        COINEX_SECRET.encode('latin-1'),
        sign_str.encode('latin-1'),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "X-COINEX-KEY": COINEX_API_KEY,
        "X-COINEX-SIGN": signature,
        "X-COINEX-TIMESTAMP": str(timestamp),
        "Content-Type": "application/json"
    }

    logging.info(f"⛔ در حال ثبت حد ضرر: {stop_price}")
    resp = requests.post(url, data=body_str, headers=headers)
    logging.info(f"SL response: {resp.text}")
    return resp.json() if resp.text else None

def set_take_profit(signal: dict, tp_price: str):
    """تنظیم حد سود پوزیشن"""
    url = "https://api.coinex.com/v2/futures/set-position-take-profit"
    method = "POST"
    timestamp = int(time.time() * 1000)

    payload = {
        "market": signal["market"],
        "market_type": "FUTURES",
        "take_profit_type": "mark_price",
        "take_profit_price": str(tp_price)
    }

    body_str = json.dumps(payload, separators=(',', ':'))
    request_path = "/v2/futures/set-position-take-profit"
    sign_str = method + request_path + body_str + str(timestamp)

    signature = hmac.new(
        COINEX_SECRET.encode('latin-1'),
        sign_str.encode('latin-1'),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "X-COINEX-KEY": COINEX_API_KEY,
        "X-COINEX-SIGN": signature,
        "X-COINEX-TIMESTAMP": str(timestamp),
        "Content-Type": "application/json"
    }

    logging.info(f"🎯 در حال ثبت حد سود: {tp_price}")
    resp = requests.post(url, data=body_str, headers=headers)
    logging.info(f"TP response: {resp.text}")
    return resp.json() if resp.text else None

# ------------------ روت تست ------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "running", "time": int(time.time())})

# ------------------ روت وبهوک ------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        signal = request.get_json(force=True)
        logging.info(f"📩 سیگنال دریافت شد: {json.dumps(signal)}")

        # 1️⃣ بررسی رمز عبور
        if signal.get("passphrase") != WEBHOOK_PASSPHRASE:
            logging.warning("❌ رمز عبور سیگنال اشتباه است")
            return jsonify({"error": "Invalid passphrase"}), 403

        # 2️⃣ جلوگیری از تکرار
        sig_key = f"{signal.get('market')}-{signal.get('side')}"
        now = time.time()
        if sig_key in last_signal and now - last_signal[sig_key] < duplicate_delay:
            logging.info("⏩ سیگنال تکراری نادیده گرفته شد")
            return jsonify({"status": "duplicate_ignored"}), 200

        last_signal[sig_key] = now

        # 3️⃣ ارسال پیام به تلگرام
        send_telegram(f"📩 New signal:\n{json.dumps(signal, indent=2)}")

        # 4️⃣ ثبت سفارش در کوینکس
        result = place_futures_order(signal)
        if result is None:
            return jsonify({"error": "Order failed"}), 500

        # 🔹 تاخیر 5 ثانیه‌ای قبل از ارسال TP/SL
        logging.info("⏳ منتظر 5 ثانیه برای ثبت TP/SL ...")
        time.sleep(5)

        # 5️⃣ ثبت حد ضرر و حد سود اول در صورت وجود
        if "stop_loss" in signal and signal["stop_loss"]:
            set_stop_loss(signal, signal["stop_loss"])

        if "take_profit_1" in signal and signal["take_profit_1"]:
            set_take_profit(signal, signal["take_profit_1"])

        logging.info("✅ عملیات ثبت سفارش و TP/SL کامل شد")
        return jsonify({"status": "order_sent", "result": result}), 200

    except Exception as e:
        logging.error(f"❌ خطا در پردازش سیگنال: {e}")
        return jsonify({"error": str(e)}), 500

# ------------------ اجرای محلی ------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
