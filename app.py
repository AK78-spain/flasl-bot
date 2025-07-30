from flask import Flask, request, jsonify
import os

app = Flask(__name__)

WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE",)  # رمز پیش‌فرض برای تست

@app.route('/')
def home():
    return "✅ Webhook Tester Running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📥 Webhook received:")
    print(data)

    if not data:
        return jsonify({"status": "error", "message": "⛔️ No JSON data received!"}), 400

    if data.get("passphrase") != WEBHOOK_PASSPHRASE:
        return jsonify({"status": "error", "message": "⛔️ Invalid passphrase!"}), 403

    return jsonify({"status": "success", "message": "✅ Webhook received successfully!"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=True)
