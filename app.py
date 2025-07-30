import os
import time
import hmac
import hashlib
import json
import logging
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import requests

# تنظیمات لاگ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(name)

# بارگذاری متغیرهای محیطی
load_dotenv()

app = Flask(name)

# تنظیمات CoinEx API
COINEX_ACCESS_ID = os.getenv('COINEX_ACCESS_ID')
COINEX_SECRET_KEY = os.getenv('COINEX_SECRET_KEY')
BASE_URL = 'https://api.coinex.com/v1/'

logger.info(f"CoinEx Bot Started - Access ID: {COINEX_ACCESS_ID[:5]}...")

# تابع امضای درخواست برای CoinEx API
def sign_request(params):
    sorted_params = sorted(params.items(), key=lambda x: x[0])
    query_string = '&'.join([f"{key}={value}" for key, value in sorted_params])
    signature = hmac.new(
        COINEX_SECRET_KEY.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature

# تابع دریافت اطلاعات بازار
def get_market_ticker(market):
    url = BASE_URL + 'market/ticker'
    params = {'market': market}
    response = requests.get(url, params=params)
    return response.json()

# تابع ارسال دستور محدود
def place_limit_order(market, order_type, amount, price):
    url = BASE_URL + 'order/limit'
    
    params = {
        'access_id': COINEX_ACCESS_ID,
        'tonce': int(time.time() * 1000),
        'market': market,
        'type': order_type,
        'amount': str(amount),
        'price': str(price)
    }
    
    signature = sign_request(params)
    
    headers = {
        'Authorization': signature,
        'Content-Type': 'application/json'
    }
    
    logger.info(f"Sending LIMIT order: {order_type.upper()} {amount} {market} @ {price}")
    response = requests.post(url, json=params, headers=headers)
    return response.json()

# تابع ارسال دستور بازار
def place_market_order(market, order_type, amount):
    url = BASE_URL + 'order/market'
    
    params = {
        'access_id': COINEX_ACCESS_ID,
        'tonce': int(time.time() * 1000),
        'market': market,
        'type': order_type,
        'amount': str(amount)
    }
    
    signature = sign_request(params)
    
    headers = {
        'Authorization': signature,
        'Content-Type': 'application/json'
    }
    
    logger.info(f"Sending MARKET order: {order_type.upper()} {amount} {market}")
    response = requests.post(url, json=params, headers=headers)
    return response.json()

# مسیر وب هوک برای دریافت سیگنال از TradingView
@app.route('/webhook', methods=['POST'])
def tradingview_webhook():
    try:
        # دریافت داده‌های JSON از TradingView
        data = request.get_json()
        
        logger.info(f"📥 Received webhook data: {json.dumps(data, indent=2)}")
        
        if not data:
            logger.error("❌ No data received from TradingView")
            return jsonify({"error": "No data received"}), 400
        
        # استخراج اطلاعات از سیگنال
        signal = data.get('signal')  # buy یا sell
        symbol = data.get('symbol')  # مثلاً BTCUSDT
        amount = data.get('amount')  # مقدار ارز
        price = data.get('price')    # قیمت (اختیاری)
        order_type = data.get('order_type', 'limit')  # limit یا market
        
        # لاگ اطلاعات مهم
        logger.info(f"📊 Signal Analysis:")
        logger.info(f"   Signal: {signal}")
        logger.info(f"   Symbol: {symbol}")
        logger.info(f"   Amount: {amount}")
        logger.info(f"   Price: {price}")
        logger.info(f"   Order Type: {order_type}")
        
        if not signal or not symbol or not amount:
            error_msg = "❌ Missing required fields: signal, symbol, amount"
            logger.error(error_msg)
            return jsonify({"error": error_msg}), 400
        
        # بررسی نوع سیگنال
        if signal.lower() not in ['buy', 'sell']:
            error_msg = "❌ Invalid signal. Must be 'buy' or 'sell'"
            logger.error(error_msg)
            return jsonify({"error": error_msg}), 400
        
        # اگر قیمت مشخص نشده، از قیمت بازار استفاده کن
        if not price:
            logger.info(f"🔍 Getting market price for {symbol}")
            ticker_data = get_market_ticker(symbol)
            if ticker_data.get('code') == 0:
                price = ticker_data['data']['ticker']['last']
                logger.info(f"💰 Market price: {price}")
            else:
                error_msg = f"❌ Failed to get market price: {ticker_data}"
                logger.error(error_msg)
                return jsonify({"error": "Failed to get market price"}), 500
        
        # ارسال دستور معامله
        logger.info(f"🚀 Executing {order_type.upper()} order...")
        if order_type == 'market':
            result = place_market_order(symbol, signal.lower(), amount)
        else:
            result = place_limit_order(symbol, signal.lower(), amount, price)
        
        # لاگ نتیجه معامله
        logger.info(f"✅ Order result: {json.dumps(result, indent=2)}")
        
        return jsonify({
            "status": "success",
            "received_data": data,
            "processed_order": {
                "signal": signal,
                "symbol": symbol,
                "amount": amount,
                "price": price,
                "order_type": order_type
            },
            "order_result": result
        })
        
    except Exception as e:
        error_msg = f"💥 Error processing webhook: {str(e)}"
        logger.error(error_msg)
        return jsonify({"error": error_msg}), 500

# مسیر برای تست سلامت سرور
@app.route('/')
def health_check():
    logger.info("🏥 Health check requested")
    return jsonify({"status": "Bot is running", "exchange": "CoinEx"})

# مسیر برای تست اتصال به CoinEx
@app.route('/test-coinex')
def test_coinex():
    try:
        logger.info("🧪 Testing CoinEx connection...")
        ticker = get_market_ticker('BTCUSDT')
        logger.info(f"✅ CoinEx test result: {json.dumps(ticker, indent=2)}")
        return jsonify(ticker)
    except Exception as e:
        error_msg = f"❌ CoinEx test failed: {str(e)}"
        logger.error(error_msg)
        return jsonify({"error": error_msg}), 500

if name == 'main':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Server starting on port {port}")
    app.run(host='0.0.0.0', port=port)
