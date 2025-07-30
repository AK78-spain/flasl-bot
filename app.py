from flask import Flask, request, jsonify
import requests
import time
import hmac
import hashlib
import os

app = Flask(__name__)

# کلیدهای API از محیط سیستم (Render یا .env)
API_KEY = os.getenv("COINEX_API_KEY")
API_SECRET = os.getenv("COINEX_API_SECRET")
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE")
API_URL = "https://api.coinex.com/v2"

# روت ساده برای تست در مرورگر
@app.route('/')
def home():
    return "✅ Bot is running!"

# روت وبهوک برای دریافت سیگنال از تریدینگ ویو
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("📥 signal TradingView:", data)

    if not data or data.get("passphrase") != WEBHOOK_PASSPHRASE:
        return jsonify({"code": "error", "message": "⛔️ رمز اشتباه یا داده نامعتبر!"}), 403

# ارسال سفارش خرید یا فروش
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

    action = data.get("action")  # buy یا sell یا close
    market = data.get("market")  # مثل BTCUSDT
    amount = data.get("amount")  # مقدار
    price = data.get("price")    # قیمت ورود

    if action not in ["buy", "sell", "close"]:
        return jsonify({"code": "error", "message": "عملیات نامعتبر"}), 400

    # اگر سیگنال close باشد، به‌طور نمادین فقط ثبت لاگ انجام می‌شود (اختیاری می‌تونی از کوینکس پوزیشن رو ببندی)
    if action == "close":
        print(f"❌ سیگنال خروج از معامله برای {market}")
        return jsonify({"code": "ok", "message": f"خروج از معامله برای {market} ثبت شد"})

    # ارسال سفارش خرید یا فروش
    result = place_order(market, action, amount, price)
    print(f"📤 سفارش {action} برای {market} به مبلغ {amount} در قیمت {price} ارسال شد")
    return jsonify(result)

# تولید امضا برای درخواست به کوینکس
POST /assets/spot/balance HTTP/1.1
Host: api.coinex.com
-H 'X-COINEX-KEY: XXXXXXXXXX' \
-H 'X-COINEX-SIGN: XXXXXXXXXX' \
-H 'X-COINEX-TIMESTAMP: 1700490703564

# اجرای لوکال برای تست
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

