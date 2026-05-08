import os
import time
import json
import requests
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

EVENT_SLUG = "btc-updown-15m-1778265900"


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


def test_polymarket_import():
    if ClobClient is None:
        return f"❌ Import Polymarket échoué : {POLY_IMPORT_ERROR}"

    try:
        ClobClient(POLY_HOST)
        return "✅ Polymarket importé. Client CLOB créé."
    except Exception as e:
        return f"⚠️ Polymarket importé, mais client non initialisé : {e}"


def get_event_by_slug(slug):
    url = f"https://gamma-api.polymarket.com/events/slug/{slug}"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.json()


def extract_first_market(event):
    markets = event.get("markets", [])

    if isinstance(markets, str):
        markets = json.loads(markets)

    if not markets:
        raise ValueError("Aucun marché trouvé dans l'event")

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
    response.raise_for_status()

    data = response.json()
    return data.get("price")


def format_price_message(event, market, outcomes, token_ids, up_price, down_price):
    title = event.get("title", "Sans titre")
    market_id = market.get("id", "N/A")
    end_date = event.get("endDate", "N/A")
    liquidity = market.get("liquidity", "N/A")
    volume = market.get("volume", "N/A")

    up_token = token_ids[0]
    down_token = token_ids[1]

    return (
        "📈 <b>BTC UP/DOWN 15M — PRIX</b>\n\n"
        f"<b>Titre :</b> {title}\n"
        f"<b>Market ID :</b> <code>{market_id}</code>\n"
        f"<b>Fin :</b> {end_date}\n"
        f"<b>Liquidité :</b> {liquidity}\n"
        f"<b>Volume :</b> {volume}\n\n"
        f"<b>Outcomes :</b> <code>{outcomes}</code>\n\n"
        f"🟢 <b>BUY Up :</b> {up_price}\n"
        f"🔴 <b>BUY Down :</b> {down_price}\n\n"
        f"<b>Up Token :</b> <code>{up_token}</code>\n"
        f"<b>Down Token :</b> <code>{down_token}</code>\n\n"
        "Aucun ordre automatique activé."
    )


def main():
    status = test_polymarket_import()

    try:
        event = get_event_by_slug(EVENT_SLUG)
        market = extract_first_market(event)

        outcomes = parse_json_field(market.get("outcomes"))
        token_ids = parse_json_field(market.get("clobTokenIds"))

        if len(outcomes) < 2 or len(token_ids) < 2:
            raise ValueError("Outcomes ou CLOB Token IDs incomplets")

        up_price = get_buy_price(token_ids[0])
        down_price = get_buy_price(token_ids[1])

        price_message = format_price_message(
            event,
            market,
            outcomes,
            token_ids,
            up_price,
            down_price
        )

    except Exception as e:
        price_message = f"❌ Erreur récupération prix : {e}"

    send_telegram(
        "🤖 <b>Bot Polymarket PRIX démarré</b>\n\n"
        f"{status}\n\n"
        f"{price_message}"
    )

    print("Bot prix en ligne. Attente active.")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
