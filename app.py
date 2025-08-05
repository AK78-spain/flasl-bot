import os
import time
import hmac
import hashlib
import json
import logging
from flask import Flask, request, jsonify
import requests

# ------------------------ تنظیمات محیطی ------------------------
COINEX_API_KEY = os.getenv("COINEX_API_KEY")
COINEX_API_SECRET = os.getenv("COINEX_API_SECRET")
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TIME_OFFSET = int(os.getenv("TIME_OFFSET", "0"))  # جبران اختلاف زمان میلی‌ثانیه

# ------------------------ تنظیم لاگر ------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

app = Flask(__name__)

last_signal_time = {}
DUPLICATE_WINDOW = 30  # ثانیه

# ------------------------ توابع کمکی ------------------------
def send_telegram_message(msg):
    """ارسال پیام به تلگرام درصورت تنظیم شدن BOT"""
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}
            )
        except Exception as e:
            logging.error(f"❌ Telegram send error: {e}")

def coinex_request(method, path, params=None):
    """ارسال درخواست به CoinEx با امضا"""
    if params is None:
        params = {}

    timestamp = int(time.time() * 1000) + TIME_OFFSET
    params["access_id"] = COINEX_API_KEY
    params["tonce"] = timestamp

    # مرتب‌سازی و امضا
    query = '&'.join(f"{k}={v}" for k, v in sorted(params.items()))
    sign = hmac.new(COINEX_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

    headers = {
        "X-COINEX-KEY": COINEX_API_KEY,
        "X-COINEX-SIGN": sign,
        "X-COINEX-TIMESTAMP": str(timestamp),
        "X-COINEX-WINDOWTIME": "60000"  # تحمل 60 ثانیه
    }

    url = f"https://api.coinex.com/v2{path}"
    if method.upper() == "GET":
        r = requests.get(url, params=params, headers=headers)
    else:
        r = requests.post(url, json=params, headers=headers)

    return r.json()

def execute_futures_order(signal):
    """ارسال سفارش به CoinEx Futures"""
    market = signal["market"]
    side = signal["side"]
    amount = signal["amount"]
    leverage = signal.get("leverage", 3)

    order_params = {
        "market": market,
        "side": side,
        "type": "market",
        "amount": str(amount),
        "leverage": leverage
    }

    logging.info(f"📤 Sending order to CoinEx: {order_params}")
    resp = coinex_request("POST", "/futures/order/put", order_params)
    logging.info(f"✅ Order response: {resp}")
    return resp

# ------------------------ روت تست ------------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "running", "time": int(time.time())})

# ------------------------ وبهوک ------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        signal = request.get_json(force=True)
        logging.info(f"📩 Received signal: {json.dumps(signal, ensure_ascii=False)}")

        # ارسال به تلگرام
        send_telegram_message(f"📩 New Signal:\n{json.dumps(signal, indent=2)}")

        # بررسی پسورد
        if signal.get("passphrase") != WEBHOOK_PASSPHRASE:
            logging.warning("❌ Invalid passphrase!")
            return jsonify({"status": "error", "msg": "Invalid passphrase"}), 403

        # جلوگیری از سیگنال تکراری
        sig_id = f"{signal['market']}-{signal['side']}"
        now = time.time()
        if sig_id in last_signal_time and now - last_signal_time[sig_id] < DUPLICATE_WINDOW:
            logging.info("⚠️ Duplicate signal ignored")
            return jsonify({"status": "ignored", "msg": "duplicate"}), 200
        last_signal_time[sig_id] = now

        # اجرای سفارش
        resp = execute_futures_order(signal)
        return jsonify(resp)

    except Exception as e:
        logging.error(f"Error processing signal: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 500

# ------------------------ اجرای برنامه ------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
