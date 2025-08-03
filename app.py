import os
import time
import json
import hashlib
import hmac
import logging
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------- تنظیمات لاگ ----------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# ---------------- تنظیمات امنیتی ----------------
API_KEY = os.getenv("COINEX_API_KEY")
API_SECRET = os.getenv("COINEX_API_SECRET")
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE", "123456")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api.coinex.com"
processed_signals = {}  # جلوگیری از سیگنال تکراری


# ---------------- توابع کمکی ----------------
def generate_signature(method, endpoint, body_dict=None):
    """تولید امضا برای CoinEx"""
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body_dict, separators=(',', ':'), ensure_ascii=False) if body_dict else ""
    prepared_str = method + endpoint + body_str + timestamp
    signature = hmac.new(
        API_SECRET.encode('latin-1'),
        prepared_str.encode('latin-1'),
        hashlib.sha256
    ).hexdigest().lower()
    return signature, timestamp


def send_telegram_message(message):
    """ارسال پیام به تلگرام"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("تلگرام تنظیم نشده است")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=5)
        logging.info("پیام تلگرام ارسال شد")
    except Exception as e:
        logging.error(f"خطا در ارسال پیام تلگرام: {str(e)}")


def adjust_leverage(market, market_type, leverage):
    """تنظیم اهرم معاملاتی"""
    endpoint = "/v2/futures/adjust-position-leverage"
    url = BASE_URL + endpoint
    body = {
        "market": market,
        "market_type": market_type,
        "margin_mode": "cross",
        "leverage": leverage
    }
    signature, timestamp = generate_signature("POST", endpoint, body)
    headers = {
        "X-COINEX-KEY": API_KEY,
        "X-COINEX-SIGN": signature,
        "X-COINEX-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=body, headers=headers, timeout=5)
        response.raise_for_status()
        result = response.json()
        logging.info(f"تنظیم اهرم موفق: {market} {leverage}x")
        return result
    except Exception as e:
        logging.error(f"خطا در تنظیم اهرم: {str(e)}")
        send_telegram_message(f"❌ خطا در تنظیم اهرم: {str(e)}")
        return None


def place_market_order(data):
    """ثبت سفارش بازار"""
    endpoint = "/v2/futures/order"
    url = BASE_URL + endpoint
    body = {
        "market": data['market'],
        "market_type": data['market_type'],
        "side": data['side'],
        "type": "market",
        "amount": str(data['amount']),
        "client_id": f"tv_{int(time.time())}"
    }

    signature, timestamp = generate_signature("PUT", endpoint, body)
    headers = {
        "X-COINEX-KEY": API_KEY,
        "X-COINEX-SIGN": signature,
        "X-COINEX-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

    try:
        response = requests.put(url, json=body, headers=headers, timeout=5)
        response.raise_for_status()
        result = response.json()
        logging.info(f"سفارش بازار ثبت شد: {result}")
        send_telegram_message(
            f"<b>✅ سفارش بازار ثبت شد</b>\n"
            f"🏷 بازار: {data['market']}\n"
            f"📈 جهت: {data['side']}\n"
            f"💰 مقدار: {data['amount']}"
        )
        return result
    except Exception as e:
        logging.error(f"خطا در ثبت سفارش بازار: {str(e)}")
        send_telegram_message(f"❌ خطا در ثبت سفارش بازار: {str(e)}")
        return None


def set_position_stop(market, market_type, stop_type, price):
    """تنظیم حد ضرر یا سود برای پوزیشن"""
    endpoint = f"/v2/futures/set-position-{stop_type}"
    url = BASE_URL + endpoint
    body = {
        "market": market,
        "market_type": market_type,
        f"{stop_type}_type": "mark_price",
        f"{stop_type}_price": str(price)
    }

    signature, timestamp = generate_signature("POST", endpoint, body)
    headers = {
        "X-COINEX-KEY": API_KEY,
        "X-COINEX-SIGN": signature,
        "X-COINEX-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=body, headers=headers, timeout=5)
        response.raise_for_status()
        result = response.json()
        logging.info(f"{stop_type} تنظیم شد: {market} قیمت {price}")
        return result
    except Exception as e:
        logging.error(f"خطا در تنظیم {stop_type}: {str(e)}")
        send_telegram_message(f"❌ خطا در تنظیم {stop_type}: {str(e)}")
        return None


def process_tradingview_signal(data):
    """پردازش سیگنال دریافتی از TradingView"""
    market_key = f"{data['market']}_{data['market_type']}_{data['side']}"

    # جلوگیری از سیگنال تکراری 5 ثانیه‌ای
    now = time.time()
    if market_key in processed_signals and now - processed_signals[market_key] < 5:
        logging.warning(f"سیگنال تکراری برای {market_key} - نادیده گرفته شد")
        return {"status": "error", "message": "سیگنال تکراری"}
    processed_signals[market_key] = now

    # 1. تنظیم اهرم
    if not adjust_leverage(data['market'], data['market_type'], data['leverage']):
        return {"status": "error", "message": "تنظیم اهرم ناموفق"}

    # 2. ثبت سفارش بازار
    if not place_market_order(data):
        return {"status": "error", "message": "ثبت سفارش ناموفق"}

    time.sleep(1)  # تاخیر کوتاه برای باز شدن پوزیشن

    # 3. تنظیم حد ضرر
    if 'stop_loss' in data:
        set_position_stop(data['market'], data['market_type'], "stop-loss", data['stop_loss'])

    # 4. تنظیم حد سود
    if 'take_profit' in data:
        set_position_stop(data['market'], data['market_type'], "take-profit", data['take_profit'])

    return {"status": "success", "message": "سیگنال پردازش شد"}


# ---------------- مسیرهای Flask ----------------
@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "service": "coinex-tradingview-webhook",
        "time": time.strftime("%Y-%m-%d %H:%M:%S")
    })


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        logging.info(f"دریافت سیگنال: {data}")

        if data.get('passphrase') != WEBHOOK_PASSPHRASE:
            logging.warning("پس‌فراز نادرست")
            return jsonify({"status": "error", "message": "مجوز نامعتبر"}), 401

        result = process_tradingview_signal(data)
        return jsonify(result)

    except Exception as e:
        logging.error(f"خطا در پردازش وب‌هوک: {str(e)}")
        send_telegram_message(f"🔥 خطای بحرانی در وب‌هوک: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ------------------ اجرای برنامه ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
