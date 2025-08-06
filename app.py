import os
import json
import time
import hmac
import hashlib
import logging
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

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
        except Exception as e:
            logging.error(f"❌ Telegram error: {e}")

def coinex_signature(payload: dict) -> dict:
    """تولید امضای کوینکس"""
    param_str = '&'.join([f"{k}={payload[k]}" for k in sorted(payload)])
    signature = hmac.new(COINEX_SECRET.encode(), param_str.encode(), hashlib.sha256).hexdigest()
    return {"X-COINEX-KEY": COINEX_API_KEY, "X-COINEX-SIGN": signature}

def place_futures_order(signal: dict):
    url = "https://api.coinex.com/v2/futures/order"
    method = "POST"
    timestamp = int(time.time() * 1000)

    # payload بدون timestamp
    payload = {
        "market": signal["market"],
        "market_type": "FUTURES",
        "side": signal["side"],
        "type": "market",
        "amount": signal["amount"],
        "leverage": signal.get("leverage", 3),
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

    logging.info(f"Sign string: {sign_str}")
    logging.info(f"Signature: {signature}")
    logging.info(f"📤 Sending order to CoinEx: {payload}")

    resp = requests.post(url, data=body_str, headers=headers)

    if resp.text.strip() == "":
        logging.error(f"❌ Empty response from CoinEx [{resp.status_code}]")
        return None

    try:
        data = resp.json()
        logging.info(f"✅ Order response: {data}")
        return data
    except Exception as e:
        logging.error(f"❌ JSON parse error: {e} | Raw: {resp.text}")
        return None


# ------------------ روت تست ------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "running", "time": int(time.time())})

# ------------------ روت وبهوک ------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        signal = request.get_json(force=True)
        logging.info(f"📩 Received signal: {json.dumps(signal)}")

        # 1️⃣ بررسی رمز عبور
        if signal.get("passphrase") != WEBHOOK_PASSPHRASE:
            logging.warning("❌ Invalid passphrase in signal")
            return jsonify({"error": "Invalid passphrase"}), 403

        # 2️⃣ جلوگیری از تکرار
        sig_key = f"{signal.get('market')}-{signal.get('side')}"
        now = time.time()
        if sig_key in last_signal and now - last_signal[sig_key] < duplicate_delay:
            logging.info("⏩ Duplicate signal ignored")
            return jsonify({"status": "duplicate_ignored"}), 200

        last_signal[sig_key] = now

        # 3️⃣ ارسال به تلگرام
        send_telegram(f"📩 New signal:\n{json.dumps(signal, indent=2)}")

        # 4️⃣ ثبت سفارش در کوینکس
        result = place_futures_order(signal)
        if result is None:
            return jsonify({"error": "Order failed"}), 500

        return jsonify({"status": "order_sent", "result": result}), 200

    except Exception as e:
        logging.error(f"❌ Error processing signal: {e}")
        return jsonify({"error": str(e)}), 500

# ------------------ اجرای محلی ------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
