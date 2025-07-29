from flask import Flask, request
import json

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json  # سیگنال ارسالی از TradingView
    print("سیگنال دریافت شد:")
    print(json.dumps(data, indent=2))

    # ✅ اینجا می‌توانید دستور معامله را اضافه کنید (بعداً)
    # مثلاً: خرید، فروش، ارسال به صرافی

    return "OK", 200

# فقط برای تست (صفحه اصلی)
@app.route('/')
def home():
    return "ربات سیگنال فعال است! 🚀"

if __name__ == '__main__':
    app.run(debug=True)
