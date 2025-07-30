from flask import Flask, request, jsonify
import requests
import time
import hmac
import hashlib
import os
import logging

# راه‌اندازی logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

app = Flask(__name__)

# کلیدهای API از محیط سیستم (Render یا فایل .env)
API_KEY = os.getenv("COINEX_API_KEY")
API_SECRET = os.getenv("COINEX_API_SECRET")
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE", "123456")
API_URL = "https://api.coinex.com/v2"

# روت ساده برای تست
@app.route('/')
def home():
    return "✅ Bot is running!"

# روت وبهوک برای دریافت سیگنال
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        logging.info("📥 Webhook received: %s", data)

        if not data or data.get("passphrase") != WEBHOOK_PASSPHRASE:
            logging.warning("⛔️ Invalid passphrase or empty data")
            return jsonify({"code": "error", "message": "⛔️ Invalid data or passphrase"}), 403

        action = data.get("action")
        market = data.get("market")
        amount = data.get("amount")
        price = data.get("price")

        if action not in ["buy", "sell", "close"]:
            return jsonify({"code": "error", "message": "❌ Invalid action"}), 400

        if action == "close":
            logging.info(f"❌ Close signal received for {market}")
            return jsonify({"code": "ok", "message": f"خروج از معامله برای {market} ثبت شد"})

        result = place_order(market, action, amount, price)
        logging.info(f"📤 Order sent: {action} {market} Amount: {amount} Price: {price}")
        return jsonify(result)

    except Exception as e:
        logging.error(f"❌ Exception in webhook: {e}")
        return jsonify({"code": "error", "message": "❌ Server error"}), 500

# امضای داده برای API کوینکس
def sign(params, secret):
    sorted_params = sorted(params.items())
    query_string = '&'.join([f"{k}={v}" for k, v in sorted_params])
    to_sign = query_string + f"&secret_key={secret}"
    signature = hashlib.md5(to_sign.encode()).hexdigest().upper()
    return signature

# ارسال سفارش به کوینکس
def place_order(market, type_, amount, price):
    endpoint = "/order/limit"
    url = API_URL + endpoint

    payload = {
        "access_id": API_KEY,
        "market": market,
        "type": type_,  # buy یا sell
        "amount": amount,
        "price": price,
        "tonce": int(time.time() * 1000)
    }

    signature = sign(payload, API_SECRET)
    headers = {
        "Authorization": signature,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    try:
        res = requests.post(url, data=payload, headers=headers)
        return res.json()
    except Exception as e:
        return {"error": str(e)}

# اجرای لوکال
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
