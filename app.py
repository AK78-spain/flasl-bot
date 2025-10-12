# filename: app.py
import os
import time
import hmac
import hashlib
import json
import logging
from flask import Flask, request, jsonify
import requests
import threading

# basic logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("bitmart-webhook-bot")

# ENV / config
BITMART_API_KEY = os.getenv("BITMART_API_KEY")
BITMART_API_SECRET = os.getenv("BITMART_API_SECRET")
BITMART_API_MEMO = os.getenv("BITMART_API_MEMO", "")
TRADINGVIEW_PASSPHRASE = os.getenv("TRADINGVIEW_PASSPHRASE", "S@leh110")
DEFAULT_LEVERAGE = os.getenv("DEFAULT_LEVERAGE", "1")

# Telegram config (required to send messages)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # ex: 123456:ABC-DEF...
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")      # ex: -1001234567890 (channel/group) or 987654321 (user)

API_BASE = "https://api-cloud-v2.bitmart.com"
SELF_PING_URL = os.getenv("SELF_PING_URL", "https://flasl-bot.onrender.com/ping")
PING_INTERVAL_SECONDS = int(os.getenv("PING_INTERVAL_SECONDS", 240))

# check keys
if not BITMART_API_KEY or not BITMART_API_SECRET:
    logger.error("BITMART_API_KEY and BITMART_API_SECRET must be set in environment variables.")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Telegram notifications will be disabled.")

app = Flask(__name__)

# map signals
SIDE_MAP = {
    "buy": 1,
    "long": 1,
    "sell": 4,
    "short": 4
}


def make_signature(timestamp_ms: int, memo: str, body_json_str: str, secret: str) -> str:
    payload = f"{timestamp_ms}#{memo}#{body_json_str}"
    h = hmac.new(secret.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256)
    return h.hexdigest()


def submit_futures_order(order_payload: dict):
    """ارسال سفارش فیوچرز به BitMart"""
    path = "/contract/private/submit-order"
    url = API_BASE + path
    body_json_str = json.dumps(order_payload, separators=(",", ":"), ensure_ascii=False)
    timestamp_ms = int(time.time() * 1000)
    sign = make_signature(timestamp_ms, BITMART_API_MEMO, body_json_str, BITMART_API_SECRET)

    headers = {
        "Content-Type": "application/json",
        "X-BM-KEY": BITMART_API_KEY,
        "X-BM-TIMESTAMP": str(timestamp_ms),
        "X-BM-SIGN": sign
    }

    logger.info("Sending order to BitMart: %s", body_json_str)
    try:
        resp = requests.post(url, headers=headers, data=body_json_str, timeout=15)
    except Exception as e:
        logger.exception("Error while sending order to BitMart")
        return False, {"error": str(e)}, None

    try:
        return (resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("application/json"), resp.json(), resp.status_code)
    except Exception:
        return (False, resp.text, resp.status_code)


# ---------------- Telegram helper ----------------
def _send_telegram_request(payload: dict):
    """درون ترد اجرا می‌شود — درخواست به تلگرام می‌فرستد"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("Telegram not configured; skipping send.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json=payload, timeout=8)
        logger.info("Telegram send status=%s resp=%s", r.status_code, r.text)
    except Exception as e:
        logger.warning("Failed to send telegram message: %s", e)


def send_telegram_message(text: str, parse_mode: str = "HTML", disable_web_page_preview: bool = True):
    """ارسال پیام به تلگرام به صورت غیرهم‌زمان"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("Telegram not configured; message not sent.")
        return

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview
    }
    t = threading.Thread(target=_send_telegram_request, args=(payload,), daemon=True)
    t.start()


def _escape_html(s: str) -> str:
    # ساده برای جلوگیری از شکستن تگ‌های HTML در parse_mode=HTML
    if not isinstance(s, str):
        s = str(s)
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))


# ---------------- Flask routes ----------------
@app.route("/webhook", methods=["POST"])
def webhook():
    """دریافت سیگنال از TradingView، ارسال سفارش و اطلاع به تلگرام"""
    data = request.get_json(silent=True)
    logger.info("Received webhook: %s", data)

    if not data:
        return jsonify({"error": "invalid json"}), 400

    if data.get("passphrase") != TRADINGVIEW_PASSPHRASE:
        logger.warning("Invalid passphrase attempt.")
        return jsonify({"error": "invalid passphrase"}), 403

    symbol = data.get("symbol")
    signal = (data.get("signal") or "").lower()
    order_type = (data.get("type") or "limit").lower()
    size = data.get("size")
    price = data.get("price", None)
    extra = data.get("extra", {})  # هر فیلد دلخواه دیگر را نگه می‌داریم

    if not symbol or not signal or not size:
        return jsonify({"error": "missing required fields (symbol, signal, size)"}), 400

    if signal not in SIDE_MAP:
        return jsonify({"error": f"unknown signal '{signal}'"}), 400

    side = SIDE_MAP[signal]

    order_payload = {
        "symbol": symbol,
        "side": side,
        "mode": 1,
        "type": order_type,
        "size": float(size),
        "leverage": str(DEFAULT_LEVERAGE),
        "open_type": "isolated",
        "client_order_id": f"tv-{int(time.time()*1000)}"
    }

    if order_type == "limit":
        if price is None:
            return jsonify({"error": "limit order requires 'price' field"}), 400
        order_payload["price"] = str(price)
    elif order_type == "market":
        pass
    else:
        if price:
            order_payload["price"] = str(price)

    # پیام اولیه به تلگرام (اعلام دریافت سیگنال)
    try:
        msg = (
            f"📩 <b>سیگنال دریافت شد</b>\n"
            f"نماد: <code>{_escape_html(symbol)}</code>\n"
            f"نوع: <b>{_escape_html(signal)}</b>\n"
            f"اندازه: <code>{_escape_html(size)}</code>\n"
            f"نوع سفارش: <code>{_escape_html(order_type)}</code>\n"
        )
        if price is not None:
            msg += f"قیمت: <code>{_escape_html(price)}</code>\n"
        if extra:
            msg += f"اطلاعات اضافی: <code>{_escape_html(json.dumps(extra, ensure_ascii=False))}</code>\n"
        send_telegram_message(msg)
    except Exception:
        logger.exception("Failed to send initial telegram message")

    # ارسال سفارش به BitMart
    success, resp_data, status = submit_futures_order(order_payload)
    logger.info("BitMart response status=%s success=%s data=%s", status, success, resp_data)

    # پیام نتیجه به تلگرام
    try:
        if success:
            tg_text = (
                f"✅ <b>سفارش ارسال شد</b>\n"
                f"نماد: <code>{_escape_html(symbol)}</code>\n"
                f"عمل: <b>{_escape_html(signal)}</b>\n"
                f"client_order_id: <code>{_escape_html(order_payload['client_order_id'])}</code>\n"
                f"پاسخ اکسچنج: <code>{_escape_html(json.dumps(resp_data, ensure_ascii=False))}</code>\n"
            )
        else:
            tg_text = (
                f"❌ <b>خطا در ارسال سفارش</b>\n"
                f"نماد: <code>{_escape_html(symbol)}</code>\n"
                f"عمل: <b>{_escape_html(signal)}</b>\n"
                f"وضعیت HTTP: {status}\n"
                f"پاسخ: <code>{_escape_html(json.dumps(resp_data, ensure_ascii=False))}</code>\n"
            )
        send_telegram_message(tg_text)
    except Exception:
        logger.exception("Failed to send result telegram message")

    if success:
        return jsonify({"ok": True, "bitmart": resp_data}), 200
    else:
        return jsonify({"ok": False, "status": status, "bitmart": resp_data}), 502


@app.route('/', methods=['GET'])
def home():
    return "RoboTrader Bot is Running!"


@app.route('/ping', methods=['POST'])
def ping():
    """برای پینگ خودکار"""
    data = request.get_json(silent=True) or {}
    if data.get("msg") == "stay awake":
        logger.info("✅ I am alive (ping received)")
        return {"status": "ok", "msg": "I am alive"}
    return {"status": "ignored"}


# 🚀 تابع پینگ خودکار
def self_ping():
    url = SELF_PING_URL
    while True:
        try:
            requests.post(url, json={"msg": "stay awake"}, timeout=10)
            logger.info("🔄 Sent self-ping to stay awake.")
        except Exception as e:
            logger.warning(f"Ping failed: {e}")
        time.sleep(PING_INTERVAL_SECONDS)


if __name__ == "__main__":
    # اجرای پینگ خودکار در پس‌زمینه
    threading.Thread(target=self_ping, daemon=True).start()

    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
