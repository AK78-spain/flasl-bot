# bitmart_webhook_bot_final.py
import os
import json
import time
import hmac
import hashlib
import logging
import requests
from flask import Flask, request, jsonify

# ---------- تنظیمات و لاگ ----------
app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ---------- متغیرهای محیطی ----------
BITMART_API_KEY = os.getenv("BITMART_API_KEY")
BITMART_API_SECRET = os.getenv("BITMART_API_SECRET")
BITMART_API_MEMO = os.getenv("BITMART_API_MEMO", "")
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE")

BASE_URL = "https://api-cloud-v2.bitmart.com"
duplicate_delay = 30  # ثانیه
last_signal = {}

# ---------- توابع کمکی ----------
def _make_signature(secret: str, timestamp: str, memo: str, body_str: str) -> str:
    """BitMart HMAC signature"""
    payload = f"{timestamp}#{memo}#{body_str}"
    sig = hmac.new(secret.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return sig

def bitmart_post(path: str, payload: dict):
    """ارسال POST به اندپوینت‌های SIGNED"""
    url = BASE_URL + path
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(payload, separators=(',', ':')) if payload else ""
    signature = _make_signature(BITMART_API_SECRET, timestamp, BITMART_API_MEMO, body_str)

    headers = {
        "Content-Type": "application/json",
        "X-BM-KEY": BITMART_API_KEY,
        "X-BM-TIMESTAMP": timestamp,
        "X-BM-SIGN": signature
    }

    logging.info(f"📤 POST {path} payload={body_str}")
    try:
        resp = requests.post(url, data=body_str, headers=headers, timeout=15)
        logging.info(f"⤵️ Response [{resp.status_code}]: {resp.text}")
        return resp.json()
    except Exception as e:
        logging.error(f"❌ خطای درخواست POST: {e}")
        return {"error": str(e)}

# ---------- عملیات معاملاتی ----------
def cancel_all_orders_for_symbol(symbol: str):
    """کنسل کردن همه سفارش‌های باز برای یک نماد"""
    path = "/contract/private/cancel-orders"
    payload = {"symbol": symbol}
    return bitmart_post(path, payload)

def place_futures_order(signal: dict):
    """ثبت سفارش بازار یا لیمیت"""
    path = "/contract/private/submit-order"
    payload = {
        "symbol": signal["symbol"],
        "type": signal.get("type", "market"),
        "side": signal["side"],
        "mode": 1,  # hedge mode
        "leverage": "1",
        "open_type": "isolated",
        "size": int(signal["size"])
    }
    if payload["type"] == "limit" and "price" in signal:
        payload["price"] = str(signal["price"])
    return bitmart_post(path, payload)

# ---------- روت‌ها ----------
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "running", "time": int(time.time())})

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        signal = request.get_json(force=True)
        logging.info(f"📩 سیگنال دریافتی: {json.dumps(signal, indent=2, ensure_ascii=False)}")

        # 1️⃣ اعتبارسنجی passphrase
        if signal.get("passphrase") != WEBHOOK_PASSPHRASE:
            logging.warning("❌ رمز سیگنال اشتباه است")
            return jsonify({"error": "Invalid passphrase"}), 403

        # 2️⃣ Mapping سیگنال buy/sell به side BitMart
        tv_side = signal.get("signal", "").lower()
        if tv_side == "buy":
            side = 1
        elif tv_side == "sell":
            side = 4
        else:
            logging.error("❌ سیگنال نامعتبر: فقط buy یا sell مجاز است")
            return jsonify({"error": "Invalid signal, must be buy or sell"}), 400
        signal["side"] = side

        # 3️⃣ جلوگیری از تکرار سیگنال
        sig_key = f"{signal.get('symbol')}-{signal['side']}-{signal.get('type','market')}"
        now = time.time()
        if sig_key in last_signal and now - last_signal[sig_key] < duplicate_delay:
            logging.info("⏩ سیگنال تکراری نادیده گرفته شد")
            return jsonify({"status": "duplicate_ignored"}), 200
        last_signal[sig_key] = now

        symbol = signal["symbol"]

        # 4️⃣ کنسل سفارش‌های باز
        logging.info("🧹 کنسل کردن سفارش‌های باز برای نماد ...")
        cancel_resp = cancel_all_orders_for_symbol(symbol)
        logging.info(f"cancel_resp: {cancel_resp}")

        # 5️⃣ صبر 1 ثانیه قبل از ثبت سفارش جدید
        time.sleep(1)

        # 6️⃣ ثبت سفارش جدید
        order_resp = place_futures_order(signal)
        logging.info(f"order_resp: {order_resp}")

        if not order_resp or order_resp.get("code") not in (0, 1000):
            logging.error("❌ ثبت سفارش موفق نبود")
            return jsonify({"error": "Order failed", "resp": order_resp}), 500

        logging.info("✅ عملیات ثبت سفارش کامل شد")
        return jsonify({"status": "order_sent", "order_resp": order_resp}), 200

    except Exception as e:
        logging.error(f"❌ خطا در پردازش وبهوک: {e}")
        return jsonify({"error": str(e)}), 500

# ---------- اجرای محلی ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
