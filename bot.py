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
        client = ClobClient(POLY_HOST)
        return "✅ Polymarket importé. Client CLOB créé."
    except Exception as e:
        return f"⚠️ Polymarket importé, mais client non initialisé : {e}"


def main():
    result = test_polymarket_import()

    send_telegram(
        "🤖 <b>Bot Polymarket démarré</b>\n"
        "Base propre active.\n\n"
        f"{result}\n\n"
        "Aucun ordre automatique activé."
    )

    print("Bot en ligne. Attente active.")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
