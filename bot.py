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
# RÈGLES JELENA V2
# =========================

REAL_TRADING_ENABLED = False

MAX_ENTRY_PRICE = 0.80
MIN_TIME_LEFT_SECONDS = 3 * 60
MAX_TIME_LEFT_SECONDS = 22 * 60

BTC_SIGNAL_THRESHOLD = 0.05
MIN_BTC_HISTORY_SECONDS = 2 * 60

CHECK_INTERVAL_SECONDS = 20
SIGNAL_COOLDOWN_SECONDS = 60

CONFIRMATION_REQUIRED = 2

price_history = deque(maxlen=80)
signal_history = deque(maxlen=5)

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
        "User-Agent": "jelena-signal-v2/1.0"
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


def get_raw_btc_signal():
    if len(price_history) < 2:
        return None, 0, "historique BTC insuffisant"

    current_time, current_price = price_history[-1]

    selected_old_price = None
    selected_old_time = None

    for timestamp, price in reversed(price_history):
        if current_time - timestamp >= MIN_BTC_HISTORY_SECONDS:
            selected_old_time = timestamp
            selected_old_price = price
            break

    if selected_old_price is None:
        return None, 0, "historique BTC trop court"

    change_pct = ((current_price - selected_old_price) / selected_old_price) * 100

    if change_pct >= BTC_SIGNAL_THRESHOLD:
        return "UP", change_pct, "variation BTC haussière"

    if change_pct <= -BTC_SIGNAL_THRESHOLD:
        return "DOWN", change_pct, "variation BTC baissière"

    return None, change_pct, "variation BTC trop faible"


def get_confirmed_signal(raw_signal):
    if raw_signal is None:
        signal_history.clear()
        return None, "aucun signal brut"

    signal_history.append(raw_signal)

    if len(signal_history) < CONFIRMATION_REQUIRED:
        return None, f"confirmation insuffisante : {list(signal_history)}"

    last_signals = list(signal_history)[-CONFIRMATION_REQUIRED:]

    if all(s == raw_signal for s in last_signals):
        return raw_signal, f"confirmation validée : {last_signals}"

    return None, f"signal instable : {last_signals}"


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


def confidence_level(change_pct):
    abs_change = abs(change_pct)

    if abs_change >= 0.15:
        return "FORTE"

    if abs_change >= 0.08:
        return "MOYENNE"

    return "FAIBLE"


def decide_signal(market_data, confirmed_signal, raw_signal_data):
    raw_signal, change_pct, raw_reason = raw_signal_data

    if market_data is None:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "price": None,
            "reason": "aucun marché BTC 15m valide trouvé"
        }

    time_left = market_data["time_left"]

    if time_left < MIN_TIME_LEFT_SECONDS:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "price": None,
            "reason": f"temps restant trop faible : {time_left // 60} min"
        }

    if time_left > MAX_TIME_LEFT_SECONDS:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "price": None,
            "reason": f"fenêtre trop tôt : {time_left // 60} min restantes"
        }

    if confirmed_signal is None:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "price": None,
            "reason": "signal non confirmé"
        }

    if confirmed_signal == "UP":
        selected_price = market_data["up_price"]
        selected_side = "UP"
    else:
        selected_price = market_data["down_price"]
        selected_side = "DOWN"

    if selected_price > MAX_ENTRY_PRICE:
        return {
            "decision": "REFUSÉ",
            "side": selected_side,
            "price": selected_price,
            "reason": f"prix trop élevé : {selected_price}"
        }

    return {
        "decision": "SIGNAL VALIDÉ",
        "side": selected_side,
        "price": selected_price,
        "reason": f"signal {selected_side} confirmé + prix OK + timing OK"
    }


def format_message(
    market_data,
    btc_price,
    raw_signal_data,
    confirmed_signal,
    confirmation_reason,
    decision_data
):
    raw_signal, change_pct, raw_reason = raw_signal_data
    confidence = confidence_level(change_pct)

    lines = [
        "🧠 <b>JELENA — SIGNAL FILTRÉ V2</b>",
        "",
        f"BTC actuel : <b>${btc_price:,.2f}</b>",
        f"Variation 2 min : <b>{change_pct:+.2f}%</b>",
        f"Signal brut : <b>{raw_signal or 'AUCUN'}</b>",
        f"Signal confirmé : <b>{confirmed_signal or 'AUCUN'}</b>",
        f"Confirmation : {confirmation_reason}",
        f"Confiance : <b>{confidence}</b>",
        "",
        "⚙️ <b>Règles actives</b>",
        f"Seuil BTC : <b>{BTC_SIGNAL_THRESHOLD}%</b>",
        f"Confirmations : <b>{CONFIRMATION_REQUIRED}</b>",
        f"Temps entrée : <b>3 à 22 min restantes</b>",
        f"Prix max : <b>{MAX_ENTRY_PRICE}</b>",
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

    if decision_data["decision"] == "SIGNAL VALIDÉ":
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
        "🤖 <b>Jelena Signal Filtré V2 démarrée</b>\n\n"
        "Mode : signal uniquement.\n"
        "Aucun ordre réel.\n\n"
        f"Seuil BTC : <b>{BTC_SIGNAL_THRESHOLD}%</b>\n"
        f"Historique : <b>2 min</b>\n"
        f"Confirmation : <b>{CONFIRMATION_REQUIRED} signaux même sens</b>\n"
        f"Temps entrée : <b>3 à 22 min restantes</b>\n"
        f"Prix max : <b>{MAX_ENTRY_PRICE}</b>\n"
        f"Check : <b>toutes les {CHECK_INTERVAL_SECONDS} sec</b>"
    )

    print("Jelena Signal Filtré V2 en ligne.")

    while True:
        try:
            btc_price = get_btc_price()
            update_btc_history(btc_price)

            raw_signal_data = get_raw_btc_signal()
            raw_signal, change_pct, raw_reason = raw_signal_data

            confirmed_signal, confirmation_reason = get_confirmed_signal(raw_signal)

            market_data = find_live_btc_15m_market()

            decision_data = decide_signal(
                market_data,
                confirmed_signal,
                raw_signal_data
            )

            message = format_message(
                market_data,
                btc_price,
                raw_signal_data,
                confirmed_signal,
                confirmation_reason,
                decision_data
            )

            print(message)

            if should_send(decision_data):
                send_telegram(message)

            time.sleep(CHECK_INTERVAL_SECONDS)

        except Exception as e:
            error_message = f"❌ Erreur Jelena V2 : {e}"
            print(error_message)
            send_telegram(error_message)
            time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
