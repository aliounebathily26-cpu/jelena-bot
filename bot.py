import os
import time
import json
import requests
from collections import deque
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

POLY_HOST = os.getenv("POLY_HOST", "https://clob.polymarket.com")

WINDOW_SECONDS = 15 * 60

# =========================
# JELENA V4 — SCALPING SIGNAL
# =========================

REAL_TRADING_ENABLED = False

# Timing marché
MIN_TIME_LEFT_SECONDS = 2 * 60
MAX_TIME_LEFT_SECONDS = 18 * 60

# Prix Polymarket
CLEAN_PRICE_MAX = 0.65
RISKY_PRICE_MAX = 0.80

# Seuils BTC scalping
WEAK_SIGNAL_THRESHOLD_2M = 0.025
STRONG_SIGNAL_THRESHOLD_2M = 0.055
MEDIUM_SIGNAL_THRESHOLD_5M = 0.07

SHORT_WINDOW_SECONDS = 2 * 60
MEDIUM_WINDOW_SECONDS = 5 * 60

CONFIRMATION_REQUIRED = 2

CHECK_INTERVAL_SECONDS = 20
SIGNAL_COOLDOWN_SECONDS = 60

price_history = deque(maxlen=120)
weak_signal_history = deque(maxlen=5)

last_sent_signal = None
last_sent_time = 0


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


def get_btc_price():
    url = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"

    headers = {
        "User-Agent": "jelena-v4-scalping/1.0"
    }

    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    data = response.json()

    if "price" not in data:
        raise ValueError(f"Réponse Coinbase invalide : {data}")

    return float(data["price"])


def update_btc_history(price):
    now = time.time()
    price_history.append((now, price))

    while price_history and now - price_history[0][0] > 15 * 60:
        price_history.popleft()


def get_change_for_window(window_seconds):
    if len(price_history) < 2:
        return None, "historique BTC insuffisant"

    current_time, current_price = price_history[-1]
    selected_old_price = None

    for timestamp, price in reversed(price_history):
        if current_time - timestamp >= window_seconds:
            selected_old_price = price
            break

    if selected_old_price is None:
        return None, f"historique BTC trop court pour {window_seconds // 60} min"

    change_pct = ((current_price - selected_old_price) / selected_old_price) * 100
    return change_pct, "OK"


def direction_from_change(change_pct, threshold):
    if change_pct is None:
        return None

    if change_pct >= threshold:
        return "UP"

    if change_pct <= -threshold:
        return "DOWN"

    return None


def get_v4_signal():
    change_2m, reason_2m = get_change_for_window(SHORT_WINDOW_SECONDS)
    change_5m, reason_5m = get_change_for_window(MEDIUM_WINDOW_SECONDS)

    if change_2m is None:
        return {
            "raw_signal": None,
            "confirmed_signal": None,
            "change_2m": 0,
            "change_5m": 0,
            "signal_type": "AUCUN",
            "reason": reason_2m,
            "confirmation": "aucune"
        }

    if change_5m is None:
        change_5m = 0

    strong_2m = direction_from_change(change_2m, STRONG_SIGNAL_THRESHOLD_2M)
    medium_5m = direction_from_change(change_5m, MEDIUM_SIGNAL_THRESHOLD_5M)
    weak_2m = direction_from_change(change_2m, WEAK_SIGNAL_THRESHOLD_2M)

    # Signal fort court terme = direct
    if strong_2m:
        weak_signal_history.clear()
        return {
            "raw_signal": strong_2m,
            "confirmed_signal": strong_2m,
            "change_2m": change_2m,
            "change_5m": change_5m,
            "signal_type": "FORT 2M",
            "reason": f"mouvement fort 2 min {strong_2m}",
            "confirmation": "validation directe"
        }

    # Signal moyen 5 minutes = direct
    if medium_5m:
        weak_signal_history.clear()
        return {
            "raw_signal": medium_5m,
            "confirmed_signal": medium_5m,
            "change_2m": change_2m,
            "change_5m": change_5m,
            "signal_type": "MOYEN 5M",
            "reason": f"mouvement moyen 5 min {medium_5m}",
            "confirmation": "validation directe"
        }

    # Signal faible = confirmation obligatoire
    if weak_2m:
        weak_signal_history.append(weak_2m)

        if len(weak_signal_history) < CONFIRMATION_REQUIRED:
            return {
                "raw_signal": weak_2m,
                "confirmed_signal": None,
                "change_2m": change_2m,
                "change_5m": change_5m,
                "signal_type": "FAIBLE 2M",
                "reason": "signal faible en attente de confirmation",
                "confirmation": f"{list(weak_signal_history)}"
            }

        last_signals = list(weak_signal_history)[-CONFIRMATION_REQUIRED:]

        if all(s == weak_2m for s in last_signals):
            return {
                "raw_signal": weak_2m,
                "confirmed_signal": weak_2m,
                "change_2m": change_2m,
                "change_5m": change_5m,
                "signal_type": "FAIBLE CONFIRMÉ",
                "reason": f"signal faible confirmé {weak_2m}",
                "confirmation": f"{last_signals}"
            }

        return {
            "raw_signal": weak_2m,
            "confirmed_signal": None,
            "change_2m": change_2m,
            "change_5m": change_5m,
            "signal_type": "INSTABLE",
            "reason": "signal faible instable",
            "confirmation": f"{last_signals}"
        }

    weak_signal_history.clear()

    return {
        "raw_signal": None,
        "confirmed_signal": None,
        "change_2m": change_2m,
        "change_5m": change_5m,
        "signal_type": "AUCUN",
        "reason": "variation BTC trop faible",
        "confirmation": "aucune"
    }


def current_15m_timestamp():
    now = int(time.time())
    return now - (now % WINDOW_SECONDS)


def generate_candidate_slugs():
    base_ts = current_15m_timestamp()
    candidates = []

    for offset in [0, 1, 2]:
        ts = base_ts + (offset * WINDOW_SECONDS)
        slug = f"btc-updown-15m-{ts}"
        candidates.append((slug, ts))

    return candidates


def get_event_by_slug(slug):
    url = f"https://gamma-api.polymarket.com/events/slug/{slug}"
    response = requests.get(url, timeout=15)

    if response.status_code == 404:
        return None

    response.raise_for_status()
    return response.json()


def extract_first_market(event):
    markets = event.get("markets", [])

    if isinstance(markets, str):
        markets = json.loads(markets)

    if not markets:
        return None

    return markets[0]


def parse_json_field(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def get_price(token_id, side):
    url = f"{POLY_HOST}/price"

    params = {
        "token_id": token_id,
        "side": side
    }

    response = requests.get(url, params=params, timeout=15)

    if response.status_code == 404:
        return None

    response.raise_for_status()

    data = response.json()
    price = data.get("price")

    if price is None:
        return None

    return float(price)


def parse_end_date(end_date):
    if not end_date:
        return None

    clean = end_date.replace("Z", "+00:00")
    return datetime.fromisoformat(clean)


def get_time_left_seconds(event):
    end_date = event.get("endDate")
    end_dt = parse_end_date(end_date)

    if not end_dt:
        return None

    now = datetime.now(timezone.utc)
    return int((end_dt - now).total_seconds())


def find_live_btc_15m_market():
    for slug, ts in generate_candidate_slugs():
        event = get_event_by_slug(slug)

        if not event:
            continue

        time_left = get_time_left_seconds(event)

        if time_left is None:
            continue

        if time_left < MIN_TIME_LEFT_SECONDS:
            continue

        market = extract_first_market(event)

        if not market:
            continue

        outcomes = parse_json_field(market.get("outcomes"))
        token_ids = parse_json_field(market.get("clobTokenIds"))

        if not outcomes or not token_ids or len(token_ids) < 2:
            continue

        up_price = get_price(token_ids[0], "BUY")
        down_price = get_price(token_ids[1], "BUY")

        if up_price is None or down_price is None:
            continue

        return {
            "slug": slug,
            "event": event,
            "market": market,
            "outcomes": outcomes,
            "token_ids": token_ids,
            "up_price": up_price,
            "down_price": down_price,
            "time_left": time_left
        }

    return None


def confidence_level(signal_data):
    abs_2m = abs(signal_data["change_2m"])
    abs_5m = abs(signal_data["change_5m"])

    if abs_2m >= 0.09 or abs_5m >= 0.12:
        return "FORTE"

    if abs_2m >= 0.055 or abs_5m >= 0.07:
        return "MOYENNE"

    if signal_data["confirmed_signal"]:
        return "FAIBLE"

    return "AUCUNE"


def decide_signal(market_data, signal_data):
    confirmed_signal = signal_data["confirmed_signal"]

    if market_data is None:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "price": None,
            "risk_level": None,
            "reason": "aucun marché BTC 15m valide trouvé"
        }

    time_left = market_data["time_left"]

    if time_left < MIN_TIME_LEFT_SECONDS:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "price": None,
            "risk_level": None,
            "reason": f"temps restant trop faible : {time_left // 60} min"
        }

    if time_left > MAX_TIME_LEFT_SECONDS:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "price": None,
            "risk_level": None,
            "reason": f"fenêtre trop tôt : {time_left // 60} min restantes"
        }

    if confirmed_signal is None:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "price": None,
            "risk_level": None,
            "reason": signal_data["reason"]
        }

    if confirmed_signal == "UP":
        selected_price = market_data["up_price"]
        selected_side = "UP"
    else:
        selected_price = market_data["down_price"]
        selected_side = "DOWN"

    if selected_price > RISKY_PRICE_MAX:
        return {
            "decision": "REFUSÉ",
            "side": selected_side,
            "price": selected_price,
            "risk_level": "TROP TARD",
            "reason": f"prix trop élevé : {selected_price}"
        }

    if selected_price <= CLEAN_PRICE_MAX:
        return {
            "decision": "SIGNAL PROPRE",
            "side": selected_side,
            "price": selected_price,
            "risk_level": "PROPRE",
            "reason": f"{signal_data['signal_type']} + prix propre + timing OK"
        }

    return {
        "decision": "SIGNAL RISQUÉ",
        "side": selected_side,
        "price": selected_price,
        "risk_level": "RISQUÉ",
        "reason": f"{signal_data['signal_type']} + prix jouable mais cher"
    }


def format_message(market_data, btc_price, signal_data, decision_data):
    confidence = confidence_level(signal_data)

    lines = [
        "⚡ <b>JELENA V4 — SCALPING SIGNAL</b>",
        "",
        f"BTC actuel : <b>${btc_price:,.2f}</b>",
        f"Variation 2 min : <b>{signal_data['change_2m']:+.3f}%</b>",
        f"Variation 5 min : <b>{signal_data['change_5m']:+.3f}%</b>",
        f"Signal brut : <b>{signal_data['raw_signal'] or 'AUCUN'}</b>",
        f"Signal confirmé : <b>{signal_data['confirmed_signal'] or 'AUCUN'}</b>",
        f"Type signal : <b>{signal_data['signal_type']}</b>",
        f"Confirmation : {signal_data['confirmation']}",
        f"Confiance : <b>{confidence}</b>",
        "",
        "⚙️ <b>Règles V4</b>",
        f"Faible 2m : <b>{WEAK_SIGNAL_THRESHOLD_2M}%</b>",
        f"Fort 2m : <b>{STRONG_SIGNAL_THRESHOLD_2M}%</b>",
        f"Moyen 5m : <b>{MEDIUM_SIGNAL_THRESHOLD_5M}%</b>",
        f"Temps entrée : <b>2 à 18 min restantes</b>",
        f"Prix propre : <b>≤ {CLEAN_PRICE_MAX}</b>",
        f"Prix risqué : <b>{CLEAN_PRICE_MAX + 0.01:.2f} à {RISKY_PRICE_MAX}</b>",
        f"Prix interdit : <b>> {RISKY_PRICE_MAX}</b>",
        f"Cooldown : <b>{SIGNAL_COOLDOWN_SECONDS} sec</b>",
        "",
    ]

    if market_data:
        event = market_data["event"]
        market = market_data["market"]
        time_left = market_data["time_left"]

        lines.extend([
            "📈 <b>Marché détecté</b>",
            f"Titre : {event.get('title', 'N/A')}",
            f"Slug : <code>{market_data['slug']}</code>",
            f"Market ID : <code>{market.get('id', 'N/A')}</code>",
            f"Temps restant : <b>{time_left // 60} min</b>",
            f"BUY Up : <b>{market_data['up_price']}</b>",
            f"BUY Down : <b>{market_data['down_price']}</b>",
            "",
        ])
    else:
        lines.append("❌ Aucun marché live valide trouvé.")
        lines.append("")

    lines.extend([
        "🎯 <b>Décision</b>",
        f"Résultat : <b>{decision_data['decision']}</b>",
        f"Side : <b>{decision_data.get('side') or 'N/A'}</b>",
        f"Prix : <b>{decision_data.get('price') or 'N/A'}</b>",
        f"Risque : <b>{decision_data.get('risk_level') or 'N/A'}</b>",
        f"Raison : {decision_data['reason']}",
        "",
        "⚠️ Mode : signal uniquement. Aucun ordre réel placé."
    ])

    return "\n".join(lines)


def should_send(decision_data):
    global last_sent_signal, last_sent_time

    now = time.time()

    signal_key = (
        f"{decision_data['decision']}|"
        f"{decision_data.get('side')}|"
        f"{decision_data.get('price')}|"
        f"{decision_data['reason']}"
    )

    if decision_data["decision"] in ["SIGNAL PROPRE", "SIGNAL RISQUÉ"]:
        if now - last_sent_time >= SIGNAL_COOLDOWN_SECONDS:
            last_sent_signal = signal_key
            last_sent_time = now
            return True
        return False

    if signal_key != last_sent_signal:
        last_sent_signal = signal_key
        last_sent_time = now
        return True

    if now - last_sent_time > 3 * 60:
        last_sent_time = now
        return True

    return False


def main():
    send_telegram(
        "🤖 <b>Jelena V4 Scalping démarrée</b>\n\n"
        "Mode : signal uniquement.\n"
        "Aucun ordre réel.\n\n"
        f"Faible 2m : <b>{WEAK_SIGNAL_THRESHOLD_2M}%</b>\n"
        f"Fort 2m : <b>{STRONG_SIGNAL_THRESHOLD_2M}%</b>\n"
        f"Moyen 5m : <b>{MEDIUM_SIGNAL_THRESHOLD_5M}%</b>\n"
        f"Temps entrée : <b>2 à 18 min restantes</b>\n"
        f"Prix propre : <b>≤ {CLEAN_PRICE_MAX}</b>\n"
        f"Prix risqué : <b>{CLEAN_PRICE_MAX + 0.01:.2f} à {RISKY_PRICE_MAX}</b>\n"
        f"Check : <b>toutes les {CHECK_INTERVAL_SECONDS} sec</b>"
    )

    print("Jelena V4 Scalping en ligne.")

    while True:
        try:
            btc_price = get_btc_price()
            update_btc_history(btc_price)

            signal_data = get_v4_signal()
            market_data = find_live_btc_15m_market()
            decision_data = decide_signal(market_data, signal_data)

            message = format_message(
                market_data,
                btc_price,
                signal_data,
                decision_data
            )

            print(message)

            if should_send(decision_data):
                send_telegram(message)

            time.sleep(CHECK_INTERVAL_SECONDS)

        except Exception as e:
            error_message = f"❌ Erreur Jelena V4 : {e}"
            print(error_message)
            send_telegram(error_message)
            time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
