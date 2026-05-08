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


def extract_markets_from_event(event):
    markets = event.get("markets", [])

    if isinstance(markets, str):
        try:
            markets = json.loads(markets)
        except Exception:
            markets = []

    return markets


def format_event_message(event, markets):
    title = event.get("title", "Sans titre")
    event_id = event.get("id", "N/A")
    slug = event.get("slug", "N/A")
    active = event.get("active", "N/A")
    closed = event.get("closed", "N/A")
    end_date = event.get("endDate", "N/A")

    lines = [
        "🎯 <b>EVENT POLYMARKET CIBLÉ</b>",
        "",
        f"<b>Titre :</b> {title}",
        f"<b>Event ID :</b> <code>{event_id}</code>",
        f"<b>Slug :</b> <code>{slug}</code>",
        f"<b>Actif :</b> {active}",
        f"<b>Fermé :</b> {closed}",
        f"<b>Fin :</b> {end_date}",
        "",
        f"Marchés associés : {len(markets)}",
        "",
    ]

    if not markets:
        lines.append("❌ Aucun marché associé trouvé dans cet event.")
        return "\n".join(lines)

    for i, market in enumerate(markets[:5], start=1):
        question = market.get("question", "Sans question")
        market_id = market.get("id", "N/A")
        condition_id = market.get("conditionId", "N/A")
        liquidity = market.get("liquidity", "N/A")
        volume = market.get("volume", "N/A")
        outcomes = market.get("outcomes", "N/A")
        clob_token_ids = market.get("clobTokenIds", "N/A")

        lines.append(f"<b>{i}. {question}</b>")
        lines.append(f"Market ID : <code>{market_id}</code>")
        lines.append(f"Condition ID : <code>{condition_id}</code>")
        lines.append(f"Liquidité : {liquidity}")
        lines.append(f"Volume : {volume}")
        lines.append(f"Outcomes : <code>{outcomes}</code>")
        lines.append(f"CLOB Token IDs : <code>{clob_token_ids}</code>")
        lines.append("")

    lines.append("Aucun ordre automatique activé.")
    return "\n".join(lines)


def main():
    status = test_polymarket_import()

    try:
        event = get_event_by_slug(EVENT_SLUG)
        markets = extract_markets_from_event(event)
        event_message = format_event_message(event, markets)
    except Exception as e:
        event_message = f"❌ Erreur lecture event ciblé : {e}"

    send_telegram(
        "🤖 <b>Bot Polymarket SLUG démarré</b>\n\n"
        f"{status}\n\n"
        f"{event_message}"
    )

    print("Bot slug en ligne. Attente active.")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
