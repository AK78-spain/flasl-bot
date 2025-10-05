# bitmart_webhook_bot.py
import os
import json
import time
import hmac
import hashlib
import logging
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------- محیطی / تنظیمات ----------
BITMART_API_KEY = os.getenv("BITMART_API_KEY")
BITMART_API_SECRET = os.getenv("BITMART_API_SECRET")
BITMART_API_MEMO = os.getenv("BITMART_API_MEMO", "")  # optional "memo" used when creating API key (can be empty)
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api-cloud-v2.bitmart.com"

# جلوگیری از تکرار سیگنال
last_signal = {}
duplicate_delay = 30  # seconds

# ---------- توابع کمکی ----------
def send_telegram(msg: str):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
            logging.info("📨 پیام به تلگرام ارسال شد")
        except Exception as e:
            logging.error(f"❌ Telegram error: {e}")

def _make_signature(secret: str, timestamp: str, memo: str, body_str: str) -> str:
    """
    BitMart signature (from docs):
    sign = hmac_sha256(secret, timestamp + '#' + memo + '#' + body)
    If memo is empty, use empty string.
    See BitMart docs for Signed endpoints. :contentReference[oaicite:2]{index=2}
    """
    payload = f"{timestamp}#{memo}#{body_str}"
    sig = hmac.new(secret.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return sig

def bitmart_post(path: str, payload: dict):
    """
    POST to signed endpoints with X-BM-KEY, X-BM-TIMESTAMP, X-BM-SIGN
    """
    url = BASE_URL + path
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(payload, separators=(',', ':')) if payload is not None else ""
    signature = _make_signature(BITMART_API_SECRET, timestamp, BITMART_API_MEMO, body_str)

    headers = {
        "Content-Type": "application/json",
        "X-BM-KEY": BITMART_API_KEY,
        "X-BM-TIMESTAMP": timestamp,
        "X-BM-SIGN": signature
    }

    logging.info(f"📤 POST {path} payload={body_str}")
    resp = requests.post(url, data=body_str, headers=headers, timeout=15)
    logging.info(f"⤵️ Response [{resp.status_code}]: {resp.text}")
    try:
        return resp.json()
    except Exception:
        return {"http_status": resp.status_code, "raw": resp.text}

def bitmart_get_keyed(path: str, params: dict = None):
    """
    GET for KEYED endpoints: usually need only X-BM-KEY (and sometimes timestamp/sign not required).
    Docs show KEYED endpoints require X-BM-KEY header. We'll include timestamp too for consistency.
    """
    url = BASE_URL + path
    timestamp = str(int(time.time() * 1000))
    headers = {
        "X-BM-KEY": BITMART_API_KEY,
        "X-BM-TIMESTAMP": timestamp
    }
    logging.info(f"🔍 GET {path} params={params}")
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    logging.info(f"⤵️ Response [{resp.status_code}]: {resp.text}")
    try:
        return resp.json()
    except Exception:
        return {"http_status": resp.status_code, "raw": resp.text}

# ---------- عملیات معاملاتی ----------
def cancel_all_orders_for_symbol(symbol: str):
    """کنسل‌کردن همه سفارش‌های باز برای آن نماد (cancel-orders endpoint)."""
    path = "/contract/private/cancel-orders"
    payload = {"symbol": symbol}
    return bitmart_post(path, payload)  # response code 1000 means submitted OK. :contentReference[oaicite:3]{index=3}

def place_futures_order(signal: dict):
    """
    ثبت سفارش بازار/لیمیت بر اساس سیگنال.
    استفاده از endpoint: /contract/private/submit-order (SIGNED). :contentReference[oaicite:4]{index=4}
    سیگنال باید حداقل شامل این فیلدها باشد:
      - market or symbol (we'll use 'symbol')
      - side (int per docs: see mapping below)
      - type ("market" or "limit")
      - size (int)
      - price (if limit)
      - mode, leverage, open_type optional depending on account
    """
    path = "/contract/private/submit-order"
    payload = {
        "symbol": signal["symbol"],
        # client_order_id optional
        "type": signal.get("type", "market"),
        "side": signal["side"],          # per docs: hedge/oneway mapping
        "mode": signal.get("mode", 1),   # default hedge mode example
        "leverage": str(signal.get("leverage", "1")),
        "open_type": signal.get("open_type", "isolated"),
        "size": int(signal["size"])
    }
    if payload["type"] == "limit":
        payload["price"] = str(signal["price"])

    return bitmart_post(path, payload)

def submit_tp_sl(signal: dict):
    """
    اگر سیگنال TP یا SL داشته باشد، از /contract/private/submit-tp-sl-order استفاده میکنیم. :contentReference[oaicite:5]{index=5}
    مستندات فیلدهای متنوعی دارند؛ اینجا یک پیاده‌سازی ساده برای ارسال trigger/executive قیمت انجام داده‌ام.
    """
    path = "/contract/private/submit-tp-sl-order"
    # نمونه payload حداقلی — ممکن است نیاز به تنظیم بر حسب strategy شما داشته باشد
    payload = {
        "symbol": signal["symbol"],
        # plan_category, price_type, category و ... ممکن است لازم باشد براساس docs تنظیم شوند
    }
    if "stop_loss" in signal:
        payload.update({
            "trigger_price": str(signal["stop_loss"]),
            "executive_price": str(signal.get("stop_loss_exec_price", signal["stop_loss"])),
            "price_type": int(signal.get("price_type", 1)),   # 1=last_price, 2=fair_price
            "plan_category": int(signal.get("plan_category", 2)),  # default per docs
            "category": signal.get("category", "limit")
        })
    if "take_profit_1" in signal:
        # اگر هم TP و SL وجود داشته باشد، می‌توانید برای هرکدام جدا payload بسازید؛
        # اینجا فقط نمونهٔ ارسال یکی از آنها نشان داده شده است
        payload.update({
            "take_profit_price": str(signal["take_profit_1"])  # توجه: فیلد دقیق را براساس docs، در صورت نیاز تنظیم کنید
        })

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

        # 1) اعتبارسنجی passphrase
        if signal.get("passphrase") != WEBHOOK_PASSPHRASE:
            logging.warning("❌ رمز سیگنال اشتباه است")
            return jsonify({"error": "Invalid passphrase"}), 403

        # 2) جلوگیری از تکرار
        sig_key = f"{signal.get('symbol')}-{signal.get('side')}-{signal.get('type','market')}"
        now = time.time()
        if sig_key in last_signal and now - last_signal[sig_key] < duplicate_delay:
            logging.info("⏩ سیگنال تکراری نادیده گرفته شد")
            return jsonify({"status": "duplicate_ignored"}), 200
        last_signal[sig_key] = now

        # 3) ارسال تلگرام دربارهٔ دریافت سیگنال
        send_telegram(f"📩 New BitMart signal:\n{json.dumps(signal, indent=2, ensure_ascii=False)}")

        symbol = signal["symbol"]

        # 4) (اختیاری اما طبق درخواست شما) کنسل همه سفارش‌های باز مخالف روی آن نماد
        logging.info("🧹 کنسل کردن سفارش‌های باز برای نماد ...")
        cancel_resp = cancel_all_orders_for_symbol(symbol)
        logging.info(f"cancel_resp: {cancel_resp}")

        # 5) صبر 1 ثانیه قبل از ثبت سفارش جدید (طبق خواسته شما)
        time.sleep(1)

        # 6) ثبت سفارش جدید
        order_resp = place_futures_order(signal)
        logging.info(f"order_resp: {order_resp}")

        if not order_resp or order_resp.get("code") not in (0, 1000):  # docs show 1000/Ok in examples
            logging.error("❌ ثبت سفارش موفق نبود")
            send_telegram(f"❌ Order failed:\n{json.dumps(order_resp, indent=2, ensure_ascii=False)}")
            return jsonify({"error": "Order failed", "resp": order_resp}), 500

        # 7) در صورت وجود TP/SL، ثبت آنها (می‌توانید بسته به نیاز چندین TP ارسال کنید)
        if "stop_loss" in signal or "take_profit_1" in signal:
            tp_sl_resp = submit_tp_sl(signal)
            logging.info(f"tp_sl_resp: {tp_sl_resp}")

        send_telegram(f"✅ Order submitted:\n{json.dumps(order_resp, indent=2, ensure_ascii=False)}")
        return jsonify({"status": "order_sent", "order_resp": order_resp}), 200

    except Exception as e:
        logging.error(f"❌ خطا در پردازش وبهوک: {e}")
        return jsonify({"error": str(e)}), 500

# ---------- اجرای محلی ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
