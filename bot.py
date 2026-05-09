import os
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PRODUCT_ID = "BTC-USD"

CHECK_INTERVAL_SECONDS = 60
ALERT_COOLDOWN_SECONDS = 8 * 60
BIAS_REMINDER_SECONDS = 25 * 60

M15_GRANULARITY = 900
H1_GRANULARITY = 3600

# Règles de clarté tendance
H1_MIN_MOVE_PCT = 0.16
H4_MIN_MOVE_PCT = 0.25

# Règles bougies M15
M15_REQUIRED_CANDLES = 3
M15_MIN_BODY_RATIO = 0.45
M15_MIN_AVG_BODY_PCT = 0.035

last_alert_key = None
last_alert_time = 0
last_bias_key = None
last_bias_time = 0


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError("Variables Telegram manquantes")

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    response = requests.post(url, json=payload, timeout=10)
    print(response.status_code, response.text)


def fetch_candles(granularity, limit=20):
    url = f"https://api.exchange.coinbase.com/products/{PRODUCT_ID}/candles"
    params = {"granularity": granularity}

    headers = {
        "User-Agent": "jelena-radar-h1-h4/1.0"
    }

    response = requests.get(url, params=params, headers=headers, timeout=10)
    response.raise_for_status()

    data = response.json()

    candles = []
    for item in data:
        # Coinbase format: [time, low, high, open, close, volume]
        candles.append({
            "time": int(item[0]),
            "low": float(item[1]),
            "high": float(item[2]),
            "open": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5])
        })

    candles.sort(key=lambda x: x["time"])
    return candles[-limit:]


def candle_direction(candle):
    if candle["close"] > candle["open"]:
        return "UP"
    if candle["close"] < candle["open"]:
        return "DOWN"
    return "NEUTRAL"


def candle_body_ratio(candle):
    total_range = candle["high"] - candle["low"]
    body = abs(candle["close"] - candle["open"])

    if total_range <= 0:
        return 0

    return body / total_range


def candle_body_pct(candle):
    if candle["open"] == 0:
        return 0

    return abs((candle["close"] - candle["open"]) / candle["open"]) * 100


def pct_move(open_price, close_price):
    if open_price == 0:
        return 0

    return ((close_price - open_price) / open_price) * 100


def analyze_h1_trend(h1_candles):
    if len(h1_candles) < 4:
        return {
            "trend": "INCONNU",
            "clear": False,
            "move_pct": 0,
            "reason": "pas assez de bougies H1"
        }

    recent = h1_candles[-4:]

    up_count = sum(1 for c in recent if candle_direction(c) == "UP")
    down_count = sum(1 for c in recent if candle_direction(c) == "DOWN")

    move = pct_move(recent[0]["open"], recent[-1]["close"])

    if up_count >= 3 and move >= H1_MIN_MOVE_PCT:
        return {
            "trend": "HAUSSIER",
            "clear": True,
            "move_pct": move,
            "reason": f"H1 clair haussier ({up_count}/4 vertes)"
        }

    if down_count >= 3 and move <= -H1_MIN_MOVE_PCT:
        return {
            "trend": "BAISSIER",
            "clear": True,
            "move_pct": move,
            "reason": f"H1 clair baissier ({down_count}/4 rouges)"
        }

    return {
        "trend": "NEUTRE",
        "clear": False,
        "move_pct": move,
        "reason": "H1 pas assez visible"
    }


def analyze_h4_trend_from_h1(h1_candles):
    if len(h1_candles) < 4:
        return {
            "trend": "INCONNU",
            "clear": False,
            "move_pct": 0,
            "reason": "pas assez de bougies pour H4"
        }

    recent = h1_candles[-4:]

    h4_open = recent[0]["open"]
    h4_close = recent[-1]["close"]
    h4_high = max(c["high"] for c in recent)
    h4_low = min(c["low"] for c in recent)

    move = pct_move(h4_open, h4_close)

    h4_candle = {
        "open": h4_open,
        "close": h4_close,
        "high": h4_high,
        "low": h4_low
    }

    ratio = candle_body_ratio(h4_candle)

    if move >= H4_MIN_MOVE_PCT and ratio >= 0.35:
        return {
            "trend": "HAUSSIER",
            "clear": True,
            "move_pct": move,
            "reason": "H4 reconstruit clairement haussier"
        }

    if move <= -H4_MIN_MOVE_PCT and ratio >= 0.35:
        return {
            "trend": "BAISSIER",
            "clear": True,
            "move_pct": move,
            "reason": "H4 reconstruit clairement baissier"
        }

    return {
        "trend": "NEUTRE",
        "clear": False,
        "move_pct": move,
        "reason": "H4 pas assez visible"
    }


def analyze_m15_trigger(m15_candles):
    if len(m15_candles) < M15_REQUIRED_CANDLES:
        return {
            "valid": False,
            "direction": None,
            "avg_body_pct": 0,
            "reason": "pas assez de bougies M15"
        }

    recent = m15_candles[-M15_REQUIRED_CANDLES:]

    directions = [candle_direction(c) for c in recent]

    if all(d == "UP" for d in directions):
        direction = "HAUSSIER"
    elif all(d == "DOWN" for d in directions):
        direction = "BAISSIER"
    else:
        return {
            "valid": False,
            "direction": None,
            "avg_body_pct": 0,
            "reason": "M15 pas aligné : les 3 bougies ne sont pas de même couleur"
        }

    body_ratios = [candle_body_ratio(c) for c in recent]
    body_pcts = [candle_body_pct(c) for c in recent]

    avg_body_pct = sum(body_pcts) / len(body_pcts)

    weak_candle = any(r < M15_MIN_BODY_RATIO for r in body_ratios)

    if weak_candle:
        return {
            "valid": False,
            "direction": direction,
            "avg_body_pct": avg_body_pct,
            "reason": "M15 refusé : au moins une bougie est trop faible"
        }

    if avg_body_pct < M15_MIN_AVG_BODY_PCT:
        return {
            "valid": False,
            "direction": direction,
            "avg_body_pct": avg_body_pct,
            "reason": "M15 refusé : bougies pas assez conséquentes"
        }

    return {
        "valid": True,
        "direction": direction,
        "avg_body_pct": avg_body_pct,
        "reason": f"3 bougies M15 fortes {direction.lower()}"
    }


def decide_radar(h1, h4, m15):
    if not h1["clear"] or not h4["clear"]:
        return {
            "state": "INTERDIT",
            "direction": "NEUTRE",
            "reason": "H1/H4 pas assez visibles"
        }

    if h1["trend"] != h4["trend"]:
        return {
            "state": "PRUDENCE",
            "direction": "CONTRADICTOIRE",
            "reason": "H1 et H4 ne sont pas alignés"
        }

    if not m15["valid"]:
        return {
            "state": "SURVEILLANCE",
            "direction": h1["trend"],
            "reason": m15["reason"]
        }

    if m15["direction"] != h1["trend"]:
        return {
            "state": "PRUDENCE",
            "direction": h1["trend"],
            "reason": "M15 va contre H1/H4"
        }

    return {
        "state": "PÉRIODE PROPRE",
        "direction": h1["trend"],
        "reason": "H4 + H1 alignés, M15 confirmé par 3 bougies fortes"
    }


def format_short_message(btc_price, h1, h4, m15, decision):
    if decision["direction"] == "HAUSSIER":
        icon = "🟢"
        action = "Surveille surtout UP."
    elif decision["direction"] == "BAISSIER":
        icon = "🔴"
        action = "Surveille surtout DOWN."
    elif decision["state"] == "PRUDENCE":
        icon = "🟠"
        action = "Prudence. Pas de direction propre."
    else:
        icon = "⚪"
        action = "Attendre. Rien à forcer."

    return (
        f"{icon} <b>JELENA RADAR</b>\n\n"
        f"État : <b>{decision['state']}</b>\n"
        f"Direction : <b>{decision['direction']}</b>\n\n"
        f"BTC : <b>${btc_price:,.2f}</b>\n"
        f"H1 : <b>{h1['trend']}</b> ({h1['move_pct']:+.2f}%)\n"
        f"H4 : <b>{h4['trend']}</b> ({h4['move_pct']:+.2f}%)\n"
        f"M15 : <b>{m15['direction'] or 'NON'}</b>\n\n"
        f"{decision['reason']}\n"
        f"{action}"
    )


def should_send(decision):
    global last_alert_key, last_alert_time, last_bias_key, last_bias_time

    now = time.time()
    key = f"{decision['state']}|{decision['direction']}|{decision['reason']}"

    if decision["state"] == "PÉRIODE PROPRE":
        if key != last_alert_key or now - last_alert_time >= ALERT_COOLDOWN_SECONDS:
            last_alert_key = key
            last_alert_time = now
            return True
        return False

    if decision["state"] in ["PRUDENCE", "SURVEILLANCE"]:
        if key != last_bias_key or now - last_bias_time >= BIAS_REMINDER_SECONDS:
            last_bias_key = key
            last_bias_time = now
            return True
        return False

    if decision["state"] == "INTERDIT":
        if key != last_bias_key and now - last_bias_time >= BIAS_REMINDER_SECONDS:
            last_bias_key = key
            last_bias_time = now
            return True
        return False

    return False


def main():
    send_telegram(
        "📡 <b>Jelena Radar H1/H4 démarrée</b>\n\n"
        "Mode : radar court.\n"
        "Aucun signal d’achat.\n"
        "Aucun ordre réel.\n\n"
        "Règles : H4 + H1 visibles, M15 = 3 bougies fortes."
    )

    print("Jelena Radar H1/H4 en ligne.")

    while True:
        try:
            m15_candles = fetch_candles(M15_GRANULARITY, limit=10)
            h1_candles = fetch_candles(H1_GRANULARITY, limit=12)

            btc_price = m15_candles[-1]["close"]

            h1 = analyze_h1_trend(h1_candles)
            h4 = analyze_h4_trend_from_h1(h1_candles)
            m15 = analyze_m15_trigger(m15_candles)

            decision = decide_radar(h1, h4, m15)

            message = format_short_message(
                btc_price,
                h1,
                h4,
                m15,
                decision
            )

            print(message)

            if should_send(decision):
                send_telegram(message)

            time.sleep(CHECK_INTERVAL_SECONDS)

        except Exception as e:
            error_message = f"❌ Erreur Jelena Radar : {e}"
            print(error_message)
            send_telegram(error_message)
            time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
