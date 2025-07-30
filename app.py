import os
import hmac
import hashlib
import time
import json
import logging
from flask import Flask, request, abort
import requests

# === تنظیمات اولیه ===
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

API_KEY = os.getenv("COINEX_API_KEY")
API_SECRET = os.getenv("COINEX_API_SECRET")
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE", "123456")

COINEX_BASE_URL = "https://api.coinex.com/v2"

# === تابع امضای درخواست (HMAC SHA256) ===
def generate_signature(api_key, api_secret, params):
    sorted_params = sorted(params.items())
    query_string = '&'.join([f"{key}={value}" for key, value in sorted_params])
    signature = hmac.new(
        api_secret.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature

# === تابع ارسال سفارش بازار (Market Order) ===
def place_futures_market_order(market, side, amount, leverage):
    url = f"{COINEX_BASE_URL}/futures/order/put-order"

    timestamp = int(time.time() * 1000)
    side_code = 1 if side == "sell" else 2
    payload = {
        "market": market,
        "market_type": "FUTURES",
        "side": side_code,
        "type": 2,  # 2 = Market Order
        "amount": amount,
        "leverage": leverage,
        "timestamp": timestamp
    }

    headers = {
        "Authorization": generate_signature(API_KEY, API_SECRET, payload),
        "AccessId": API_KEY,
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, json=payload)
    logging.info(f"Market order response: {response.json()}")
    return response.json()

# === تابع تنظیم حد سود / حد ضرر ===
def set_stop_orders(market, side, amount, tp_price, sl_price):
    url = f"{COINEX_BASE_URL}/futures/order/put-stop-order"

    timestamp = int(time.time() * 1000)
    side_code = 1 if side == "sell" else 2
    stop_type = 1  # latest price

    orders = []

    if tp_price:
        orders.append({
            "market": market,
            "market_type": "FUTURES",
            "side": side_code,
            "stop_type": stop_type,
            "amount": amount,
            "stop_price": tp_price,
            "effect_type": 1,
            "timestamp": timestamp
        })

    if sl_price:
        orders.append({
            "market": market,
            "market_type": "FUTURES",
            "side": side_code,
            "stop_type": stop_type,
            "amount": amount,
            "stop_price": sl_price,
            "effect_type": 1,
            "timestamp": timestamp
        })

    for order in orders:
        headers = {
            "Authorization": generate_signature(API_KEY, API_SECRET, order),
            "AccessId": API_KEY,
            "Content-Type": "application/json"
        }

        response = requests.post(url, headers=headers, json=order)
        logging.info(f"Stop order response: {response.json()}")

# === مسیر اصلی دریافت سیگنال از تریدینگ‌ویو ===
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    logging.info(f"Received data: {data}")

    if not data or data.get('passphrase') != WEBHOOK_PASSPHRASE:
        logging.warning("Invalid passphrase or empty data.")
        return abort(403)

    try:
        market = data['market']
        side = data['side']
        order_type = data['type']
        amount = data['amount']
        leverage = data.get('leverage', 3)
        tp = data.get('take_profit_1')
        sl = data.get('stop_loss')

        if order_type == "market":
            order_response = place_futures_market_order(market, side, amount, leverage)
            if order_response.get('code') == 0:
                set_stop_orders(market, side, amount, tp, sl)
                return {"status": "success", "message": "Order placed and TP/SL set."}, 200
            else:
                return {"status": "error", "message": order_response}, 400
        else:
            return {"status": "error", "message": "Only market orders supported now."}, 400

    except Exception as e:
        logging.error(f"Error processing webhook: {str(e)}")
        return {"status": "error", "message": str(e)}, 500

# === اجرای برنامه در Render ===
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
