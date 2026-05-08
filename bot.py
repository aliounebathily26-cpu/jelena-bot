import os
import time
import json
import requests
from collections import deque
from datetime import datetime, timezone
from dotenv import load_dotenv

try:
    from py_clob_client.client import ClobClient
except Exception as e:
    ClobClient = None
    POLY_IMPORT_ERROR = str(e)
else:
    POLY_IMPORT_ERROR = None


load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

POLY_HOST = os.getenv("POLY_HOST", "https://clob.polymarket.com")
POLY_PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY")
POLY_CHAIN_ID = int(os.getenv("POLY_CHAIN_ID", "137"))
POLY_FUNDER_ADDRESS = os.getenv("POLY_FUNDER_ADDRESS")
POLY_SIGNATURE_TYPE = int(os.getenv("POLY_SIGNATURE_TYPE", "1"))

WINDOW_SECONDS = 15 * 60

MAX_ENTRY_PRICE = 0.70
MIN_TIME_LEFT_SECONDS = 5 * 60
MAX_TIME_LEFT_SECONDS = 13 * 60

BTC_SIGNAL_THRESHOLD = 0.20
MIN_BTC_HISTORY_SECONDS = 3 * 60

CHECK_INTERVAL_SECONDS = 60

price_history = deque(maxlen=30)
last_sent_decision = None
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


def test_polymarket_auth():
    if ClobClient is None:
        return f"❌ Module Polymarket non importé : {POLY_IMPORT_ERROR}"

    if not POLY_PRIVATE_KEY:
        return "❌ POLY_PRIVATE_KEY manquant."

    if not POLY_FUNDER_ADDRESS:
        return "❌ POLY_FUNDER_ADDRESS manquant."

    try:
        temp_client = ClobClient(
            POLY_HOST,
            key=POLY_PRIVATE_KEY,
            chain_id=POLY_CHAIN_ID,
            signature_type=POLY_SIGNATURE_TYPE,
            funder=POLY_FUNDER_ADDRESS
        )

        creds = temp_client.create_or_derive_api_creds()

        client = ClobClient(
            POLY_HOST,
            key=POLY_PRIVATE_KEY,
            chain_id=POLY_CHAIN_ID,
            creds=creds,
            signature_type=POLY_SIGNATURE_TYPE,
            funder=POLY_FUNDER_ADDRESS
        )

        if client is None:
            return "❌ Client trading non créé."

        return "✅ Auth Polymarket OK. Client trading initialisé. Aucun ordre placé."

    except Exception as e:
        return f"❌ Auth Polymarket échouée : {e}"


def get_btc_price():
    url = "https://api.bybit.com/v5/market/tickers"

    params = {
        "category": "spot",
        "symbol": "BTCUSDT"
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()

    if data.get("retCode") != 0:
        raise ValueError(f"Erreur Bybit : {data}")

    ticker = data["result"]["list"][0]
    return float(ticker["lastPrice"])


def update_btc_history(price):
    now = time.time()
    price_history.append((now, price))

    while price_history and now - price_history[0][0] > 15 * 60:
        price_history.popleft()


def get_btc_signal():
    if len(price_history) < 2:
        return None, 0, "historique BTC insuffisant"

    current_time, current_price = price_history[-1]
    oldest_time, oldest_price = price_history[0]

    age = current_time - oldest_time

    if age < MIN_BTC_HISTORY_SECONDS:
        return None, 0, "historique BTC trop court"

    change_pct = ((current_price - oldest_price) / oldest_price) * 100

    if change_pct >= BTC_SIGNAL_THRESHOLD:
        return "UP", change_pct, "variation BTC haussière"

    if change_pct <= -BTC_SIGNAL_THRESHOLD:
        return "DOWN", change_pct, "variation BTC baissière"

    return None, change_pct, "variation BTC trop faible"


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


def get_buy_price(token_id):
    url = f"{POLY_HOST}/price"

    params = {
        "token_id": token_id,
        "side": "BUY"
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

        up_price = get_buy_price(token_ids[0])
        down_price = get_buy_price(token_ids[1])

        if up_price is None or down_price is None:
            continue

        return {
            "slug": slug,
            "timestamp": ts,
            "event": event,
            "market": market,
            "outcomes": outcomes,
            "token_ids": token_ids,
            "up_price": up_price,
            "down_price": down_price,
            "time_left": time_left
        }

    return None


def decide_trade(market_data, btc_signal):
    signal, change_pct, signal_reason = btc_signal

    if market_data is None:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "reason": "aucun marché BTC 15m valide trouvé"
        }

    time_left = market_data["time_left"]

    if time_left < MIN_TIME_LEFT_SECONDS:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "reason": f"temps restant trop faible : {time_left // 60} min"
        }

    if time_left > MAX_TIME_LEFT_SECONDS:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "reason": f"fenêtre trop tôt : {time_left // 60} min restantes"
        }

    if signal is None:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "reason": signal_reason
        }

    if signal == "UP":
        selected_price = market_data["up_price"]
        selected_side = "UP"
        selected_token = market_data["token_ids"][0]
    else:
        selected_price = market_data["down_price"]
        selected_side = "DOWN"
        selected_token = market_data["token_ids"][1]

    if selected_price > MAX_ENTRY_PRICE:
        return {
            "decision": "REFUSÉ",
            "side": selected_side,
            "reason": f"prix trop élevé : {selected_price}"
        }

    return {
        "decision": "ACHAT AUTORISÉ",
        "side": selected_side,
        "price": selected_price,
        "token_id": selected_token,
        "reason": f"signal {selected_side} + prix OK + temps OK"
    }


def format_message(market_data, btc_price, btc_signal, decision_data):
    signal, change_pct, signal_reason = btc_signal

    lines = [
        "🧠 <b>BOT POLYMARKET — DÉCISION AUTO</b>",
        "",
        f"BTC actuel : <b>${btc_price:,.2f}</b>",
        f"Signal BTC : <b>{signal or 'AUCUN'}</b>",
        f"Variation : <b>{change_pct:+.2f}%</b>",
        f"Raison signal : {signal_reason}",
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
        "⚙️ <b>Décision</b>",
        f"Résultat : <b>{decision_data['decision']}</b>",
        f"Side : <b>{decision_data.get('side') or 'N/A'}</b>",
        f"Raison : {decision_data['reason']}",
        "",
        "⚠️ Aucun ordre placé."
    ])

    return "\n".join(lines)


def should_send(decision_data):
    global last_sent_decision, last_sent_time

    now = time.time()
    decision_key = f"{decision_data['decision']}|{decision_data.get('side')}|{decision_data['reason']}"

    if decision_data["decision"] == "ACHAT AUTORISÉ":
        return True

    if decision_key != last_sent_decision:
        last_sent_decision = decision_key
        last_sent_time = now
        return True

    if now - last_sent_time > 5 * 60:
        last_sent_time = now
        return True

    return False


def main():
    auth_status = test_polymarket_auth()

    send_telegram(
        "🤖 <b>Bot Polymarket décision auto démarré</b>\n\n"
        f"{auth_status}\n\n"
        "Source BTC : Bybit.\n"
        "Mode actuel : décision automatique seulement.\n"
        "Aucun ordre réel activé."
    )

    print("Bot décision auto en ligne.")

    while True:
        try:
            btc_price = get_btc_price()
            update_btc_history(btc_price)

            btc_signal = get_btc_signal()
            market_data = find_live_btc_15m_market()
            decision_data = decide_trade(market_data, btc_signal)

            message = format_message(
                market_data,
                btc_price,
                btc_signal,
                decision_data
            )

            print(message)

            if should_send(decision_data):
                send_telegram(message)

            time.sleep(CHECK_INTERVAL_SECONDS)

        except Exception as e:
            error_message = f"❌ Erreur bot décision auto : {e}"
            print(error_message)
            send_telegram(error_message)
            time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
