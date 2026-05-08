import os
import time
import json
import requests
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

    return "✅ Polymarket importé."


def test_polymarket_auth():
    if ClobClient is None:
        return "❌ Auth impossible : module Polymarket non importé."

    if not POLY_PRIVATE_KEY:
        return "❌ Auth impossible : POLY_PRIVATE_KEY manquant."

    if not POLY_FUNDER_ADDRESS:
        return "❌ Auth impossible : POLY_FUNDER_ADDRESS manquant."

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

        # Petit test sans ordre : on vérifie que le client L2 existe.
        if client is None:
            return "❌ Auth échouée : client L2 non créé."

        return (
            "✅ Auth Polymarket réussie.\n"
            "✅ API credentials dérivés.\n"
            "✅ Client trading initialisé.\n"
            "⚠️ Aucun ordre placé."
        )

    except Exception as e:
        return f"❌ Auth Polymarket échouée : {e}"


def current_15m_timestamp():
    now = int(time.time())
    return now - (now % WINDOW_SECONDS)


def generate_candidate_slugs():
    base_ts = current_15m_timestamp()
    candidates = []

    for offset in [-1, 0, 1, 2]:
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

    return data.get("price")


def find_live_btc_15m_market():
    checked = []

    for slug, ts in generate_candidate_slugs():
        event = get_event_by_slug(slug)

        if not event:
            checked.append(f"{slug} → introuvable")
            continue

        market = extract_first_market(event)

        if not market:
            checked.append(f"{slug} → aucun marché")
            continue

        outcomes = parse_json_field(market.get("outcomes"))
        token_ids = parse_json_field(market.get("clobTokenIds"))

        if not outcomes or not token_ids or len(token_ids) < 2:
            checked.append(f"{slug} → token IDs incomplets")
            continue

        up_price = get_buy_price(token_ids[0])
        down_price = get_buy_price(token_ids[1])

        if up_price is None or down_price is None:
            checked.append(f"{slug} → prix indisponibles")
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
            "checked": checked
        }

    return {
        "slug": None,
        "checked": checked
    }


def format_market_message(data):
    if not data.get("slug"):
        lines = [
            "❌ <b>Aucun marché BTC Up/Down 15m actif trouvé</b>",
            "",
            "Slugs testés :",
        ]

        for item in data.get("checked", []):
            lines.append(f"- {item}")

        return "\n".join(lines)

    event = data["event"]
    market = data["market"]

    title = event.get("title", "Sans titre")
    market_id = market.get("id", "N/A")
    end_date = event.get("endDate", "N/A")
    liquidity = market.get("liquidity", "N/A")
    volume = market.get("volume", "N/A")

    ts_readable = datetime.fromtimestamp(
        data["timestamp"],
        tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    return (
        "📈 <b>BTC UP/DOWN 15M — LIVE</b>\n\n"
        f"<b>Titre :</b> {title}\n"
        f"<b>Slug actif :</b> <code>{data['slug']}</code>\n"
        f"<b>Timestamp :</b> {ts_readable}\n"
        f"<b>Market ID :</b> <code>{market_id}</code>\n"
        f"<b>Fin :</b> {end_date}\n"
        f"<b>Liquidité :</b> {liquidity}\n"
        f"<b>Volume :</b> {volume}\n\n"
        f"🟢 <b>BUY Up :</b> {data['up_price']}\n"
        f"🔴 <b>BUY Down :</b> {data['down_price']}\n"
    )


def main():
    import_status = test_polymarket_import()
    auth_status = test_polymarket_auth()

    try:
        market_data = find_live_btc_15m_market()
        market_message = format_market_message(market_data)
    except Exception as e:
        market_message = f"❌ Erreur marché live : {e}"

    send_telegram(
        "🤖 <b>Bot Polymarket AUTH démarré</b>\n\n"
        f"{import_status}\n\n"
        f"{auth_status}\n\n"
        f"{market_message}\n\n"
        "Aucun ordre automatique activé."
    )

    print("Bot auth en ligne. Attente active.")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
