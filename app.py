from flask import Flask, request
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/webhook', methods=['POST'])
def webhook():
   data = request.get_json(force=True)
    
    # 🔍 این خط پیام رو در لاگ چاپ می‌کنه
    print("📩 Webhook received:", data)
    
    return "✅ Webhook received", 200

# 🔻 این بخش حیاتی است 🔻
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
