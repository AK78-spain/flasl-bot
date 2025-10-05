# app.py

from flask import Flask, request, jsonify
import hashlib
import hmac
import time
import requests
import os
import json

app = Flask(__name__)

# --- BitMart API Configuration ---
# این مقادیر رو باید از طریق متغیرهای محیطی (Environment Variables) در Render بگیریم
API_KEY = os.environ.get('BITMART_API_KEY')
SECRET_KEY = os.environ.get('BITMART_SECRET_KEY')
BITMART_MEMO = os.environ.get('BITMART_MEMO') # همون passphrase API Key
WEBHOOK_PASSPHRASE = os.environ.get('WEBHOOK_PASSPHRASE') # چک کلید برای webhook

if not API_KEY or not SECRET_KEY or not BITMART_MEMO or not WEBHOOK_PASSPHRASE:
    raise ValueError("لطفاً متغیرهای محیطی BITMART_API_KEY، BITMART_SECRET_KEY، BITMART_MEMO و WEBHOOK_PASSPHRASE را تنظیم کنید.")

BASE_URL = 'https://api-cloud-v2.bitmart.com'

# --- Utility Functions ---

def get_timestamp():
    return int(time.time() * 1000)

def sign_request(method, url_path, body_str, timestamp, secret_key):
    """تابع امضای درخواست بر اساس مستندات BitMart"""
    # توجه: طبق مستندات، برای امضای درخواست‌های REST، از 'X-BM-TIMESTAMP#MEMO#BODY' استفاده می‌شه
    str_to_sign = f"{timestamp}#{BITMART_MEMO}#{body_str}"
    signature = hmac.new(
        key=bytes(secret_key, "utf-8"), # secret_key به بایت تبدیل می‌شه
        msg=bytes(str_to_sign, "utf-8"), # str_to_sign به بایت تبدیل می‌شه
        digestmod=hashlib.sha256
    ).digest() # خروجی digest() یه ترتیب بایتی (bytes) هست
    signature_hex = signature.hex() # تبدیل به رشته Hexadecimal
    return signature_hex

def submit_order(symbol, side_int, price, size, leverage, order_type='limit', mode=1):
    """
    ثبت یک اوردر فیوچرز
    :param symbol: مثل 'BTCUSDT'
    :param side_int: 1=buy_open_long, 4=sell_open_short (hedge mode)
    :param price: قیمت اوردر (برای limit order)
    :param size: تعداد قرارداد (int)
    :param leverage: اهرم (string)
    :param order_type: 'limit' یا 'market'
    :param mode: 1=GTC, 2=FOK, 3=IOC, 4=Maker Only
    :return: پاسخ API
    """
    timestamp = get_timestamp()
    url_path = '/contract/private/submit-order'

    # Body ارسالی به API
    # توجه: open_type حذف شد چون گفتی اجباری نیست
    body_dict = {
        "symbol": symbol,
        "side": side_int,
        "type": order_type,
        "leverage": leverage, # اینجا string می‌خواد
        "mode": mode,
        "size": size # اینجا int می‌خواد
    }

    if order_type == 'limit':
        body_dict["price"] = price

    body_str = json.dumps(body_dict) # تبدیل به رشته JSON

    # ایجاد امضا
    signature = sign_request('POST', url_path, body_str, timestamp, SECRET_KEY)

    # Headers درخواست
    headers = {
        'X-BM-KEY': API_KEY,
        'X-BM-SIGN': signature, # این signature همین signature_hex هست که تابع sign_request برمی‌گردونه
        'X-BM-TIMESTAMP': str(timestamp),
        'X-BM-PERMS': BITMART_MEMO, # استفاده از BITMART_MEMO برای X-BM-PERMS
        'Content-Type': 'application/json'
    }

    # ارسال درخواست
    api_url = BASE_URL + url_path
    try:
        response = requests.post(api_url, headers=headers, data=body_str)
        response.raise_for_status() # اگر status code 2xx نبود، ارور می‌ده
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"خطا در ارسال درخواست به BitMart: {e}")
        if response is not None:
            print(f"متن پاسخ خطا: {response.text}")
            try:
                error_details = response.json()
                print(f"Detalii پاسخ خطا: {error_details}")
            except:
                print("پاسخ خطا JSON نبود.")
        return {"error": f"Request failed: {e}"}
    except Exception as e:
        print(f"خطای غیرمنتظره: {e}")
        return {"error": f"Unexpected error: {e}"}


# --- Webhook Route ---

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        # دریافت JSON از TradingView
        data = request.get_json()

        if not 
            print("هیچ داده‌ای در webhook دریافت نشد.")
            return jsonify({"error": "No data received"}), 400

        print(f"Webhook دریافت شد: {data}")

        # --- چک کردن Passphrase ---
        received_passphrase = data.get('passphrase')
        if received_passphrase != WEBHOOK_PASSPHRASE:
            print(f"رمز webhook اشتباه است. دریافتی: {received_passphrase}, انتظار می‌رفت: {WEBHOOK_PASSPHRASE}")
            # لاگ می‌زنه که رمز اشتباه بود
            return jsonify({"error": "Invalid passphrase"}), 403 # Forbidden

        # --- پردازش داده‌ها ---
        tv_symbol = data.get('symbol', '').upper() # مثلاً 'BTCUSDT'
        tv_signal = data.get('signal', '').lower() # مثلاً 'buy' یا 'sell'
        tv_order_type = data.get('type', '').lower() # مثلاً 'limit' یا 'market'
        tv_price = data.get('price', '') # مثلاً '60000'
        tv_size_str = data.get('size', '0') # مثلاً '100' (string)
        tv_leverage_str = data.get('leverage', '5') # مثلاً '5' (string) - فرض می‌کنیم یه فیلد leverage هم داریم یا یه مقدار پیش‌فرض

        # تبدیل size و leverage به نوع مناسب
        try:
            tv_size = int(tv_size_str)
            tv_leverage = str(tv_leverage_str) # API string می‌خواد
        except ValueError:
            print(f"مقدار size یا leverage قابل تبدیل نیست. size: {tv_size_str}, leverage: {tv_leverage_str}")
            return jsonify({"error": "Invalid size or leverage format"}), 400

        if not tv_symbol or not tv_signal or not tv_order_type or (tv_order_type == 'limit' and not tv_price) or tv_size <= 0:
            print("داده‌های webhook ناقص یا نامعتبر است.")
            return jsonify({"error": "Incomplete or invalid data"}), 400

        # چک کردن نوع اوردر
        if tv_order_type not in ['limit', 'market']:
            print(f"نوع اوردر '{tv_order_type}' معتبر نیست.")
            return jsonify({"error": f"Invalid order type: {tv_order_type}"}), 400

        # تبدیل signal به عدد مورد نیاز BitMart (hedge mode)
        # 1=buy_open_long, 4=sell_open_short
        side_map = {
            'buy': 1,
            'buy_long': 1,
            'sell': 4,
            'sell_short': 4,
        }
        side_int = side_map.get(tv_signal)
        if side_int is None:
            print(f"Signal '{tv_signal}' معتبر نیست.")
            return jsonify({"error": f"Invalid signal: {tv_signal}"}), 400

        # فراخوانی تابع ثبت اوردر
        result = submit_order(
            symbol=tv_symbol,
            side_int=side_int,
            price=tv_price,
            size=tv_size,
            leverage=tv_leverage,
            order_type=tv_order_type, # 'limit' یا 'market'
            mode=1 # GTC
        )

        print(f"نتیجه ثبت اوردر: {result}")

        # برگرداندن پاسخ به TradingView
        if 'error' in result:
            # اگر ثبت اوردر مشکل داشت
            return jsonify(result), 500
        else:
            # اگر ثبت اوردر موفقیت‌آمیز بود
            return jsonify({"status": "success", "order_result": result}), 200

    else:
        # فقط POST قبول شود
        return jsonify({"error": "Method not allowed"}), 405

@app.route('/', methods=['GET'])
def home():
    return "RoboTrader Bot is Running!"

if __name__ == '__main__':
    # فقط برای تست محلی. روی Render از Gunicorn یا مشابهش استفاده می‌شه.
    # PORT متغیر محیطی‌ه که Render به اپ شما می‌ده
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False) # debug رو false بذار توی محیط production
