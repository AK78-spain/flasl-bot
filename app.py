# filename: app.py
import os
import time
import hmac
import hashlib
import json
import logging
from flask import Flask, request, jsonify
import requests

# basic logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("bitmart-webhook-bot")

# Config from environment
BITMART_API_KEY = os.getenv("BITMART_API_KEY")
BITMART_API_SECRET = os.getenv("BITMART_API_SECRET")
BITMART_API_MEMO = os.getenv("BITMART_API_MEMO", "")  # memo set when creating API key
TRADINGVIEW_PASSPHRASE = os.getenv("TRADINGVIEW_PASSPHRASE", "S@leh110")
DEFAULT_LEVERAGE = os.getenv("DEFAULT_LEVERAGE", "1")  # string on purpose

API_BASE = "https://api-cloud-v2.bitmart.com"

# Basic checks
if not BITMART_API_KEY or not BITMART_API_SECRET:
    logger.error("BITMART_API_KEY and BITMART_API_SECRET must be set in environment variables.")

app = Flask(__name__)

# map TradingView signal to BitMart side (user requested: buy->1, sell->4)
SIDE_MAP = {
    "buy": 1,
    "long": 1,
    "sell": 4,
    "short": 4
}

def make_signature(timestamp_ms: int, memo: str, body_json_str: str, secret: str) -> str:
    """
    Per BitMart docs:
    X-BM-SIGN = HMAC_SHA256(secret, f"{timestamp}#{memo}#{body_json}")
    body_json must be exactly the JSON string sent (no extra spaces ideally).
    """
    payload = f"{timestamp_ms}#{memo}#{body_json_str}"
    h = hmac.new(secret.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256)
    return h.hexdigest()

def submit_futures_order(order_payload: dict):
    """
    Submits to /contract/private/submit-order
    Returns (success_bool, response_json_or_text, status_code)
    """
    path = "/contract/private/submit-order"
    url = API_BASE + path

    # body JSON string: use separators to avoid spaces (consistent with signature)
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
    resp = requests.post(url, headers=headers, data=body_json_str, timeout=15)
    try:
        return (resp.status_code == 200 and resp.headers.get("Content-Type","").startswith("application/json"), resp.json(), resp.status_code)
    except Exception:
        return (False, resp.text, resp.status_code)

@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Endpoint to receive TradingView webhook (POST JSON)
    Expected body:
    {
      "passphrase": "S@leh110",
      "symbol": "BTCUSDT",
      "signal": "buy",
      "type": "limit",
      "price": "...",      # required for limit
      "size": "100"
    }
    """
    data = request.get_json(silent=True)
    logger.info("Received webhook: %s", data)

    if not data:
        return jsonify({"error": "invalid json"}), 400

    # validate passphrase
    if data.get("passphrase") != TRADINGVIEW_PASSPHRASE:
        logger.warning("Invalid passphrase attempt.")
        return jsonify({"error": "invalid passphrase"}), 403

    # required fields
    symbol = data.get("symbol")
    signal = (data.get("signal") or "").lower()
    order_type = (data.get("type") or "limit").lower()
    size = data.get("size")
    price = data.get("price", None)  # for limit

    if not symbol or not signal or not size:
        return jsonify({"error": "missing required fields (symbol, signal, size)"}), 400

    if signal not in SIDE_MAP:
        return jsonify({"error": f"unknown signal '{signal}'"}), 400

    side = SIDE_MAP[signal]  # 1 or 4 as requested

    # Build order payload according to BitMart docs.
    # Minimal safe payload: symbol, side, mode, type, size, (price if limit), leverage, open_type optional.
    # mode: 1 (open?) — keep default 1 as in docs examples. open_type: "isolated" by default, can be changed.
    order_payload = {
        "symbol": symbol,
        "side": side,
        "mode": 1,
        "type": order_type,
        "size": int(size),
        "leverage": str(DEFAULT_LEVERAGE),    # string per examples
        # optional defaults:
        "open_type": "isolated"
    }

    if order_type == "limit":
        if price is None:
            return jsonify({"error": "limit order requires 'price' field"}), 400
        order_payload["price"] = str(price)
    elif order_type == "market":
        # market orders often don't need price
        pass
    else:
        # allow other types if provided, pass-through
        if price:
            order_payload["price"] = str(price)

    # optional client_order_id to help idempotency (timestamp-based)
    order_payload["client_order_id"] = f"tv-{int(time.time()*1000)}"

    success, resp_data, status = submit_futures_order(order_payload)
    logger.info("BitMart response status=%s success=%s data=%s", status, success, resp_data)

    if success:
        return jsonify({"ok": True, "bitmart": resp_data}), 200
    else:
        return jsonify({"ok": False, "status": status, "bitmart": resp_data}), 502

@app.route('/', methods=['GET'])
def home():
    return "RoboTrader Bot is Running!"
    
if __name__ == "__main__":
    # for local testing
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
