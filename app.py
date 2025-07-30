from flask import Flask, request, jsonify
import logging
import os

# تنظیم logging برای نمایش پیام‌ها در همه محیط‌ها (مثل Render)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

app = Flask(__name__)

# دریافت از محیط یا مقدار پیش‌فرض
WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE")

@app.route('/')
def home():
    return "✅ Webhook Server is Running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        logging.info("📥 Webhook received from TradingView:")
        logging.info(data)

        if not data or data.get("passphrase") != WEBHOOK_PASSPHRASE:
            logging.warning("⛔️ Invalid data or passphrase")
            return jsonify({"code": "error", "message": "⛔️ Invalid data or passphrase"}), 403

        return jsonify({"code": "success", "message": "✅ Webhook received"}), 200

    except Exception as e:
        logging.error(f"🚨 Error in webhook: {e}")
        return jsonify({"code": "error", "message": "❌ Server error"}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
