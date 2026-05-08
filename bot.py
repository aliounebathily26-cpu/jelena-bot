import os
import time
import json
import requests
from collections import deque
from datetime import datetime, timezone
from dotenv import load_dotenv
import socks
import socket
socks.set_default_proxy(socks.SOCKS5, "us-az-92.protonvpn.net", 1080, username="1ybYPdUVooeza87Q", password="ClZyqXYgEwNmpETLuY7mFVj7XN0vRDq6")
socket.socket = socks.socksocket

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import MarketOrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL
except Exception as e:
    ClobClient = None
    MarketOrderArgs = None
    OrderType = None
    BUY = "BUY"
    SELL = "SELL"
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

REAL_TRADING_ENABLED = True
TRADE_AMOUNT_USD = 1.00

MAX_ENTRY_PRICE = 0.75
MIN_TIME_LEFT_SECONDS = 4 * 60
MAX_TIME_LEFT_SECONDS = 20 * 60

BTC_SIGNAL_THRESHOLD = 0.05
MIN_BTC_HISTORY_SECONDS = 2 * 60

TAKE_PROFIT_MULTIPLIER = 1.30
EXIT_BEFORE_END_SECONDS = 90

MAX_TRADES_PER_DAY = 5
MAX_LOSSES_PER_DAY = 2

CHECK_INTERVAL_SECONDS = 30
STATE_FILE = "bot_state.json"

price_history = deque(maxlen=40)
poly_client = None
last_sent_decision = None
last_sent_time = 0


def load_state():
    default_state = {
        "current_position": None,
        "traded_markets": [],
        "trades_today": 0,
        "losses_today": 0,
        "day": datetime.now(timezone.utc).strftime("%Y-%m-%d")
    }

    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
    except Exception:
        return default_state

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if state.get("day") != today:
        state["day"] = today
        state["trades_today"] = 0
        state["losses_today"] = 0
        state["traded_markets"] = []
        state["current_position"] = None

    return state


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


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


def init_polymarket_client():
    global poly_client

    if ClobClient is None:
        raise ValueError(f"Module Polymarket non importé : {POLY_IMPORT_ERROR}")

    if not POLY_PRIVATE_KEY:
        raise ValueError("POLY_PRIVATE_KEY manquant")

    if not POLY_FUNDER_ADDRESS:
        raise ValueError("POLY_FUNDER_ADDRESS manquant")

    temp_client = ClobClient(
        POLY_HOST,
        key=POLY_PRIVATE_KEY,
        chain_id=POLY_CHAIN_ID,
        signature_type=POLY_SIGNATURE_TYPE,
        funder=POLY_FUNDER_ADDRESS
    )

    creds = temp_client.create_or_derive_api_creds()

    poly_client = ClobClient(
        POLY_HOST,
        key=POLY_PRIVATE_KEY,
        chain_id=POLY_CHAIN_ID,
        creds=creds,
        signature_type=POLY_SIGNATURE_TYPE,
        funder=POLY_FUNDER_ADDRESS
    )

    return poly_client


def get_btc_price():
    url = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"

    headers = {
        "User-Agent": "jelena-polymarket-bot/1.0"
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


def decide_trade(market_data, btc_signal, state):
    signal, change_pct, signal_reason = btc_signal

    if state["current_position"] is not None:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "reason": "position déjà ouverte"
        }

    if state["trades_today"] >= MAX_TRADES_PER_DAY:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "reason": "limite trades journalière atteinte"
        }

    if state["losses_today"] >= MAX_LOSSES_PER_DAY:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "reason": "stop après 2 pertes journalières"
        }

    if market_data is None:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "reason": "aucun marché BTC 15m valide trouvé"
        }

    market_id = str(market_data["market"].get("id"))

    if market_id in state["traded_markets"]:
        return {
            "decision": "REFUSÉ",
            "side": None,
            "reason": "marché déjà tradé"
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


def place_market_buy(token_id, amount_usd):
    order_args = MarketOrderArgs(
        token_id=token_id,
        amount=float(amount_usd),
        side=BUY
    )

    signed_order = poly_client.create_market_order(order_args)
    response = poly_client.post_order(signed_order, OrderType.FOK)

    return response


def place_market_sell(token_id, shares):
    order_args = MarketOrderArgs(
        token_id=token_id,
        amount=float(shares),
        side=SELL
    )

    signed_order = poly_client.create_market_order(order_args)
    response = poly_client.post_order(signed_order, OrderType.FOK)

    return response


def open_position(market_data, decision_data, state):
    market = market_data["market"]
    event = market_data["event"]

    token_id = decision_data["token_id"]
    side = decision_data["side"]
    entry_price = float(decision_data["price"])
    market_id = str(market.get("id"))

    response = place_market_buy(token_id, TRADE_AMOUNT_USD)

    estimated_shares = round((TRADE_AMOUNT_USD / entry_price) * 0.98, 4)
    take_profit_price = round(entry_price * TAKE_PROFIT_MULTIPLIER, 4)

    position = {
        "market_id": market_id,
        "slug": market_data["slug"],
        "title": event.get("title", "N/A"),
        "side": side,
        "token_id": token_id,
        "entry_price": entry_price,
        "take_profit_price": take_profit_price,
        "amount_usd": TRADE_AMOUNT_USD,
        "estimated_shares": estimated_shares,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "end_date": event.get("endDate"),
        "buy_response": str(response)
    }

    state["current_position"] = position
    state["traded_markets"].append(market_id)
    state["trades_today"] += 1
    save_state(state)

    send_telegram(
        "🟢 <b>ACHAT RÉEL PLACÉ</b>\n\n"
        f"Marché : {position['title']}\n"
        f"Side : <b>{side}</b>\n"
        f"Montant : <b>{TRADE_AMOUNT_USD}$</b>\n"
        f"Prix entrée estimé : <b>{entry_price}</b>\n"
        f"Objectif +30% : <b>{take_profit_price}</b>\n"
        f"Shares estimées : <b>{estimated_shares}</b>\n\n"
        f"Réponse achat : <code>{str(response)[:800]}</code>"
    )


def manage_position(state):
    position = state.get("current_position")

    if not position:
        return

    token_id = position["token_id"]
    entry_price = float(position["entry_price"])
    take_profit_price = float(position["take_profit_price"])
    estimated_shares = float(position["estimated_shares"])

    sell_price = get_price(token_id, "SELL")

    if sell_price is None:
        return

    end_dt = parse_end_date(position["end_date"])
    now = datetime.now(timezone.utc)
    time_left = int((end_dt - now).total_seconds()) if end_dt else 999999

    should_exit = False
    exit_reason = None

    if sell_price >= take_profit_price:
        should_exit = True
        exit_reason = f"take profit atteint : {sell_price} >= {take_profit_price}"

    elif time_left <= EXIT_BEFORE_END_SECONDS:
        should_exit = True
        exit_reason = f"sortie sécurité avant fin : {time_left} sec restantes"

    if not should_exit:
        return

    response = place_market_sell(token_id, estimated_shares)

    pnl_pct = ((sell_price - entry_price) / entry_price) * 100

    if pnl_pct < 0:
        state["losses_today"] += 1

    closed_position = state["current_position"]
    state["current_position"] = None
    save_state(state)

    send_telegram(
        "🔴 <b>SORTIE POSITION</b>\n\n"
        f"Side : <b>{closed_position['side']}</b>\n"
        f"Prix entrée : <b>{entry_price}</b>\n"
        f"Prix sortie estimé : <b>{sell_price}</b>\n"
        f"PnL estimé : <b>{pnl_pct:+.2f}%</b>\n"
        f"Raison : {exit_reason}\n\n"
        f"Réponse vente : <code>{str(response)[:800]}</code>"
    )


def format_decision_message(market_data, btc_price, btc_signal, decision_data, state):
    signal, change_pct, signal_reason = btc_signal

    lines = [
        "🧠 <b>BOT POLYMARKET — RÉEL 1$</b>",
        "",
        f"BTC actuel : <b>${btc_price:,.2f}</b>",
        f"Signal BTC : <b>{signal or 'AUCUN'}</b>",
        f"Variation : <b>{change_pct:+.2f}%</b>",
        f"Raison signal : {signal_reason}",
        "",
        f"Trades aujourd’hui : <b>{state['trades_today']}/{MAX_TRADES_PER_DAY}</b>",
        f"Pertes aujourd’hui : <b>{state['losses_today']}/{MAX_LOSSES_PER_DAY}</b>",
        "",
    ]

    if state.get("current_position"):
        pos = state["current_position"]
        lines.extend([
            "📌 <b>Position ouverte</b>",
            f"Side : <b>{pos['side']}</b>",
            f"Prix entrée : <b>{pos['entry_price']}</b>",
            f"Objectif : <b>{pos['take_profit_price']}</b>",
            f"Shares estimées : <b>{pos['estimated_shares']}</b>",
            "",
        ])

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
        "⚠️ Trading réel activé : 1$ max par trade."
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
    global poly_client

    state = load_state()
    poly_client = init_polymarket_client()

    send_telegram(
        "🤖 <b>Bot Polymarket RÉEL 1$ démarré</b>\n\n"
        "✅ Auth Polymarket OK.\n"
        "✅ Trading réel activé.\n\n"
        f"Montant : <b>{TRADE_AMOUNT_USD}$</b>\n"
        f"Seuil BTC : <b>{BTC_SIGNAL_THRESHOLD}%</b>\n"
        f"Temps entrée : <b>4 à 20 min restantes</b>\n"
        f"Prix max entrée : <b>{MAX_ENTRY_PRICE}</b>\n"
        f"Take profit : <b>+30%</b>\n"
        f"Sortie sécurité : <b>90 sec avant fin</b>\n"
        f"Max trades/jour : <b>{MAX_TRADES_PER_DAY}</b>\n"
        f"Stop pertes/jour : <b>{MAX_LOSSES_PER_DAY}</b>"
    )

    print("Bot réel 1$ en ligne.")

    while True:
        try:
            state = load_state()

            manage_position(state)

            btc_price = get_btc_price()
            update_btc_history(btc_price)

            btc_signal = get_btc_signal()
            market_data = find_live_btc_15m_market()
            decision_data = decide_trade(market_data, btc_signal, state)

            if decision_data["decision"] == "ACHAT AUTORISÉ" and REAL_TRADING_ENABLED:
                open_position(market_data, decision_data, state)

            message = format_decision_message(
                market_data,
                btc_price,
                btc_signal,
                decision_data,
                state
            )

            print(message)

            if should_send(decision_data):
                send_telegram(message)

            time.sleep(CHECK_INTERVAL_SECONDS)

        except Exception as e:
            error_message = f"❌ Erreur bot réel 1$ : {e}"
            print(error_message)
            send_telegram(error_message)
            time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main() 
