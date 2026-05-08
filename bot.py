import os
import time
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


def get_all_active_markets():
    url = "https://gamma-api.polymarket.com/markets"

    params = {
        "active": "true",
        "closed": "false",
        "limit": 1000
    }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()

    return response.json()


def get_debug_btc_markets():
    markets = get_all_active_markets()
    btc_markets = []

    for market in markets:
        question = market.get("question", "") or ""
        title = market.get("title", "") or ""
        slug = market.get("slug", "") or ""

        text = f"{question} {title} {slug}".lower()

        if "btc" in text or "bitcoin" in text:
            btc_markets.append(market)

    return btc_markets[:20]


def format_debug_message(markets):
    if not markets:
        return (
            "🔍 <b>DEBUG BTC POLYMARKET</b>\n\n"
            "Aucun marché contenant BTC ou Bitcoin trouvé dans les 1000 premiers marchés actifs.\n\n"
            "Conclusion : il faudra chercher autrement."
        )

    lines = [
        "🔍 <b>DEBUG BTC POLYMARKET</b>",
        "",
        f"Marchés trouvés : {len(markets)}",
        "",
    ]

    for i, market in enumerate(markets, start=1):
        question = market.get("question", "Sans question")
        title = market.get("title", "Sans titre")
        slug = market.get("slug", "N/A")
        market_id = market.get("id", "N/A")
        end_date = market.get("endDate", "N/A")

        lines.append(f"<b>{i}. {question}</b>")
        lines.append(f"Title : {title}")
        lines.append(f"Slug : <code>{slug}</code>")
        lines.append(f"ID : <code>{market_id}</code>")
        lines.append(f"Fin : {end_date}")
        lines.append("")

    lines.append("Aucun ordre automatique activé.")
    return "\n".join(lines)


def main():
    status = test_polymarket_import()

    try:
        markets = get_debug_btc_markets()
        debug_message = format_debug_message(markets)
    except Exception as e:
        debug_message = f"❌ Erreur debug marchés Polymarket : {e}"

    send_telegram(
        "🤖 <b>Bot Polymarket DEBUG démarré</b>\n\n"
        f"{status}\n\n"
        f"{debug_message}"
    )

    print("Bot debug en ligne. Attente active.")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
