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


def is_btc_up_down_short_term_market(market):
    question = market.get("question", "") or ""
    title = market.get("title", "") or ""
    slug = market.get("slug", "") or ""

    text = f"{question} {title} {slug}".lower()

    btc_words = ["btc", "bitcoin"]
    direction_words = ["up or down", "up/down", "up", "down"]
    short_term_words = [
        "15m",
        "15 min",
        "15 minute",
        "15-minute",
        "15 minutes",
        "hour",
        "1 hour",
        "today",
        "daily"
    ]

    bad_words = [
        "gta",
        "$1m",
        "1m",
        "million",
        "before",
        "2027",
        "2028",
        "2029",
        "2030",
        "election",
        "etf",
        "reserve",
        "country",
        "company"
    ]

    has_btc = any(word in text for word in btc_words)
    has_direction = any(word in text for word in direction_words)
    has_short_term = any(word in text for word in short_term_words)
    has_bad_word = any(word in text for word in bad_words)

    return has_btc and has_direction and has_short_term and not has_bad_word


def get_polymarket_btc_updown_markets():
    url = "https://gamma-api.polymarket.com/markets"

    params = {
        "active": "true",
        "closed": "false",
        "limit": 500
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()

    markets = response.json()

    filtered_markets = []

    for market in markets:
        if is_btc_up_down_short_term_market(market):
            filtered_markets.append(market)

    return filtered_markets[:10]


def format_markets_message(markets):
    if not markets:
        return (
            "📊 <b>Marchés BTC Up/Down court terme</b>\n\n"
            "Aucun marché BTC Up/Down court terme trouvé.\n\n"
            "Possibilités :\n"
            "- le marché n'est pas dans les 500 premiers résultats\n"
            "- le nom du marché est différent\n"
            "- le filtre est encore trop strict\n\n"
            "Aucun ordre automatique activé."
        )

    lines = [
        "📊 <b>Marchés BTC Up/Down court terme détectés</b>",
        "",
    ]

    for i, market in enumerate(markets, start=1):
        question = market.get("question", "Sans titre")
        market_id = market.get("id", "N/A")
        liquidity = market.get("liquidity", "N/A")
        volume = market.get("volume", "N/A")
        end_date = market.get("endDate", "N/A")
        slug = market.get("slug", "N/A")

        lines.append(f"<b>{i}. {question}</b>")
        lines.append(f"ID : <code>{market_id}</code>")
        lines.append(f"Slug : <code>{slug}</code>")
        lines.append(f"Liquidité : {liquidity}")
        lines.append(f"Volume : {volume}")
        lines.append(f"Fin : {end_date}")
        lines.append("")

    lines.append("Aucun ordre automatique activé.")
    return "\n".join(lines)


def main():
    status = test_polymarket_import()

    try:
        markets = get_polymarket_btc_updown_markets()
        markets_message = format_markets_message(markets)
    except Exception as e:
        markets_message = f"❌ Erreur lecture marchés Polymarket : {e}"

    send_telegram(
        "🤖 <b>Bot Polymarket démarré</b>\n"
        "Recherche BTC Up/Down court terme.\n\n"
        f"{status}\n\n"
        f"{markets_message}"
    )

    print("Bot en ligne. Attente active.")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
