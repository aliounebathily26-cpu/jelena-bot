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


def get_polymarket_btc_markets():
    """
    Lecture publique uniquement.
    Aucun wallet.
    Aucun ordre.
    Aucun trade.
    """
    url = "https://gamma-api.polymarket.com/markets"

    params = {
        "active": "true",
        "closed": "false",
        "limit": 100
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()

    markets = response.json()

    btc_markets = []

    for market in markets:
        question = market.get("question", "")
        title = market.get("title", "")
        text = f"{question} {title}".lower()

        if (
            "bitcoin" in text
            or "btc" in text
            or ("up" in text and "down" in text)
        ):
            btc_markets.append(market)

    return btc_markets[:5]


def format_markets_message(markets):
    if not markets:
        return (
            "📊 <b>Marchés BTC Polymarket</b>\n\n"
            "Aucun marché BTC Up/Down trouvé dans les 100 premiers marchés actifs.\n\n"
            "Aucun ordre automatique activé."
        )

    lines = [
        "📊 <b>Marchés BTC Polymarket détectés</b>",
        "",
    ]

    for i, market in enumerate(markets, start=1):
        question = market.get("question", "Sans titre")
        market_id = market.get("id", "N/A")
        liquidity = market.get("liquidity", "N/A")
        volume = market.get("volume", "N/A")
        end_date = market.get("endDate", "N/A")

        lines.append(f"<b>{i}. {question}</b>")
        lines.append(f"ID : <code>{market_id}</code>")
        lines.append(f"Liquidité : {liquidity}")
        lines.append(f"Volume : {volume}")
        lines.append(f"Fin : {end_date}")
        lines.append("")

    lines.append("Aucun ordre automatique activé.")
    return "\n".join(lines)


def main():
    status = test_polymarket_import()

    try:
        markets = get_polymarket_btc_markets()
        markets_message = format_markets_message(markets)
    except Exception as e:
        markets_message = f"❌ Erreur lecture marchés Polymarket : {e}"

    send_telegram(
        "🤖 <b>Bot Polymarket démarré</b>\n"
        "Base propre active.\n\n"
        f"{status}\n\n"
        f"{markets_message}"
    )

    print("Bot en ligne. Attente active.")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
