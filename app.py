import os
import hashlib
import hmac
import time
import json
import logging
from datetime import datetime
from functools import wraps

import requests
from flask import Flask, request, jsonify

# تنظیم logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# تنظیم Flask
app = Flask(__name__)

# --- تنظیمات API و محیط ---
API_KEY = os.getenv("COINEX_API_KEY")
API_SECRET = os.getenv("COINEX_API_SECRET")
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE", "123456")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # اختیاری
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")      # اختیاری

# پایه API
BASE_URL = "https://api.coinex.com"

# --- ذخیره آخرین سیگنال برای جلوگیری از تکرار (در حافظه) ---
last_signals = {}  # key: market+side, value: timestamp
COOLDOWN = 5  # ثانیه


def send_telegram(message):
    """ارسال پیام به تلگرام (در صورت تنظیم توکن و چت آیدی)"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        logger.warning(f"Failed to send Telegram message: {e}")


def is_duplicate_signal(market, side):
    """بررسی اینکه آیا در 5 ثانیه گذشته سیگنال مشابهی دریافت شده؟"""
    key = f"{market}:{side}"
    now = time.time()
    if key in last_signals:
        if now - last_signals[key] < COOLDOWN:
            return True
    last_signals[key] = now
    return False


def sign_request(method, path, body, timestamp):
    """
    ایجاد امضای HMAC-SHA256 برای درخواست API
    """
    # آماده‌سازی رشته امضا
    prepared_str = method.upper() + path
    if body:
        prepared_str += json.dumps(body, separators=(',', ':'), ensure_ascii=False)
    prepared_str += str(timestamp)

    # ایجاد امضا
    signature = hmac.new(
        API_SECRET.encode('latin-1'),
        prepared_str.encode('latin-1'),
        hashlib.sha256
    ).hexdigest().lower()
    return signature


def make_coinex_request(method, endpoint, data=None):
    """
    ارسال درخواست به API کوینکس با احراز هویت
    """
    if not API_KEY or not API_SECRET:
        logger.error("API credentials not set.")
        return None

    url = BASE_URL + endpoint
    timestamp = int(time.time() * 1000)
    headers = {
        'X-COINEX-KEY': API_KEY,
        'X-COINEX-SIGN': sign_request(method, endpoint, data, timestamp),
        'X-COINEX-TIMESTAMP': str(timestamp),
        'Content-Type': 'application/json'
    }

    try:
        response = requests.request(method, url, headers=headers, json=data, timeout=10)
        result = response.json()
        logger.info(f"API Response [{endpoint}]: {result}")
        if result.get("code") == 0:
            return result.get("data")
        else:
            error_msg = result.get("message", "Unknown error")
            logger.error(f"API Error [{endpoint}]: {error_msg}")
            send_telegram(f"❌ API Error: {error_msg}")
            return None
    except Exception as e:
        logger.error(f"Request failed [{endpoint}]: {e}")
        send_telegram(f"⚠️ Request failed: {e}")
        return None


@app.route('/')
def home():
    """برای تست لایو بودن سرور"""
    return jsonify({"status": "running", "time": datetime.utcnow().isoformat()}), 200


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"Received webhook: {data}")

        # اعتبارسنجی JSON
        if not 
            return jsonify({"error": "No data"}), 400

        # اعتبارسنجی passphrase
        if data.get("passphrase") != WEBHOOK_PASSPHRASE:
            logger.warning("Invalid passphrase")
            return jsonify({"error": "Invalid passphrase"}), 403

        # استخراج فیلدها
        market = data.get("market")
        market_type = data.get("market_type", "FUTURES")
        side = data.get("side")  # buy/sell
        amount = float(data.get("amount", 0))
        leverage = int(data.get("leverage", 5))
        stop_loss = data.get("stop_loss")
        take_profit_1 = data.get("take_profit_1")
        take_profit_2 = data.get("take_profit_2")

        if not all([market, side, amount > 0]):
            logger.error("Missing required fields")
            return jsonify({"error": "Missing required fields"}), 400

        # جلوگیری از تکرار
        if is_duplicate_signal(market, side):
            logger.info(f"Duplicate signal ignored: {market} {side}")
            return jsonify({"status": "duplicate ignored"}), 200

        # تعیین نوع سفارش: buy = long, sell = short
        order_side = "open_long" if side.lower() == "buy" else "open_short"
        logger.info(f"Processing {order_side} for {market} with amount={amount}")

        # مرحله 1: تنظیم اهرم
        leverage_data = {
            "market": market,
            "market_type": market_type,
            "margin_mode": "cross",  # یا "isolated"
            "leverage": leverage
        }
        leverage_result = make_coinex_request(
            "POST", "/v2/futures/adjust-position-leverage", leverage_data
        )
        if leverage_result is None:
            send_telegram(f"⚠️ Failed to set leverage for {market}")
        else:
            send_telegram(f"✅ Leverage set to {leverage}x for {market}")

        # مرحله 2: باز کردن پوزیشن (سفارش مارکت)
        order_data = {
            "market": market,
            "market_type": market_type,
            "side": order_side,
            "order_type": "market",
            "amount": str(amount)
        }
        order_result = make_coinex_request("POST", "/v2/futures/order/put-order", order_data)
        if order_result is None:
            send_telegram(f"❌ Failed to open position: {market}")
            return jsonify({"error": "Failed to open position"}), 500

        # مرحله 3: تنظیم حد ضرر (Stop Loss)
        if stop_loss:
            sl_data = {
                "market": market,
                "market_type": market_type,
                "stop_loss_type": "mark_price",
                "stop_loss_price": str(stop_loss)
            }
            sl_result = make_coinex_request("POST", "/v2/futures/position/set-position-stop-loss", sl_data)
            if sl_result is not None:
                send_telegram(f"🛡️ Stop Loss set at {stop_loss} for {market}")

        # مرحله 4: تنظیم حد سود (Take Profit)
        # می‌توانید چند حد سود داشته باشید، اما API فقط یکی را می‌پذیرد
        # پس اولین حد سود را تنظیم می‌کنیم
        take_profit = take_profit_1 or take_profit_2
        if take_profit:
            tp_data = {
                "market": market,
                "market_type": market_type,
                "take_profit_type": "mark_price",
                "take_profit_price": str(take_profit)
            }
            tp_result = make_coinex_request("POST", "/v2/futures/position/set-position-take-profit", tp_data)
            if tp_result is not None:
                send_telegram(f"🎯 Take Profit set at {take_profit} for {market}")

        # پیام نهایی موفقیت
        msg = f"""
✅ Position Opened!
Market: {market}
Side: {side.upper()}
Amount: {amount}
Leverage: {leverage}x
"""
        if stop_loss:
            msg += f"Stop Loss: {stop_loss}\n"
        if take_profit:
            msg += f"Take Profit: {take_profit}\n"
        send_telegram(msg)

        return jsonify({"status": "success", "position": "opened"}), 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        send_telegram(f"🚨 Webhook error: {e}")
        return jsonify({"error": "Internal error"}), 500

# ------------------ اجرای برنامه ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
