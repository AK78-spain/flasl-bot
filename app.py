# bitmart_futures_webhook_bot.py
import os
import json
import time
import hmac
import hashlib
import logging
import requests
from flask import Flask, request, jsonify

# ---------- تنظیمات ----------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

BITMART_API_KEY = os.getenv("BITMART_API_KEY")
BITMART_API_SECRET = os.getenv("BITMART_API_SECRET")
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE")
BASE_URL = "https://api-cloud-v2.bitmart.com"

duplicate_delay = 30  # ثانیه برای جلوگیری از سیگنال تکراری
last_signal = {}

# ---------- ساخت امضا ----------
def make_signature(secret: str, timestamp: str, body_str: str) -> str:
    """
    ساخت امضا برای BitMart Futures
    Memo خالی → استفاده از دو علامت #
    """
    payload = f"{timestamp}##{body_str}"
    signature = hmac.new(secret.encode('utf-8'),
                         payload.encode('utf-8'),
                         hashlib.sha256).hexdigest()
    return signature

# ---------- ارسال درخواست POST ----------
def bitmart_post(path: str, payload: dict):
    """ارسال درخواست POST با امضای معتبر"""
    url = BASE_URL + path
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(payload, separators=(',', ':'))
    signature = make_signature(BITMART_API_SECRET, timestamp, body_str)

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
        logging.error(f"❌ خطای ارسال درخواست: {e}")
        return {"error": str(e)}

# ---------- ثبت سفارش ----------
def place_order(signal: dict):
    """ارسال سفارش جدید بر اساس سیگنال"""
    path = "/contract/private/submit-order"

    # تبدیل نوع سیگنال تریدینگ‌ویو به کد BitMart
    side_map = {
        "buy": 1,   # buy_open_long
        "sell": 4   # sell_open_short
    }

    side = side_map.get(signal.get("signal", "").lower())
    if not side:
        raise ValueError("سیگنال نامعتبر است (فقط 'buy' یا 'sell')")

    payload = {
        "symbol": signal["symbol"],
        "type": signal.get("type", "limit"),
        "side": side,
        "mode": 1,              # hedge mode
        "leverage": "1",
        "open_type": "isolated",
        "size": int(signal["size"])
    }

    if payload["type"] == "limit":
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
        logging.info(f"📩 سیگنال دریافتی:\n{json.dumps(signal, indent=2, ensure_ascii=False)}")

        # بررسی رمز عبور
        if signal.get("passphrase") != WEBHOOK_PASSPHRASE:
            logging.warning("❌ رمز سیگنال اشتباه است")
            return jsonify({"error": "Invalid passphrase"}), 403

        # جلوگیری از تکرار سیگنال
        sig_key = f"{signal.get('symbol')}-{signal.get('signal')}-{signal.get('type','limit')}"
        now = time.time()
        if sig_key in last_signal and now - last_signal[sig_key] < duplicate_delay:
            logging.info("⏩ سیگنال تکراری نادیده گرفته شد")
            return jsonify({"status": "duplicate_ignored"}), 200
        last_signal[sig_key] = now

        # ارسال سفارش جدید
        order_resp = place_order(signal)
        logging.info(f"order_resp: {order_resp}")

        if not order_resp or order_resp.get("code") not in (0, 1000):
            logging.error("❌ ثبت سفارش موفق نبود")
            return jsonify({"error": "Order failed", "resp": order_resp}), 500

        logging.info("✅ سفارش با موفقیت ثبت شد")
        return jsonify({"status": "order_sent", "order_resp": order_resp}), 200

    except Exception as e:
        logging.error(f"❌ خطا در پردازش وبهوک: {e}")
        return jsonify({"error": str(e)}), 500

# ---------- اجرای لوکال ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
