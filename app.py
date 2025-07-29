from flask import Flask, request
import json

app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    return 'Bot is running!'

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("Received Webhook:", data)

    # اینجا کدی برای اجرای معامله می‌گذاری
    # مثلاً:
    # if data['action'] == 'buy':
    #     execute_trade('buy')

    return 'Webhook received', 200
