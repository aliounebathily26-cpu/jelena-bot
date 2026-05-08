import requests
import time
import datetime
from collections import deque

TELEGRAM_TOKEN = "8539436833:AAEbwacljaENAab9bkdn2VY7OMoov503GPQ"
CHAT_ID = "8754609023"
COINGECKO_KEY = "CG-4XBTEsUxjpA9RbpgcX8nZRgF"
THRESHOLD = 0.4

price_history = deque(maxlen=20)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_btc_price():
    url = "https://api.coingecko.com/api/v3/simple/price"
    headers = {"x-cg-demo-api-key": COINGECKO_KEY}
    params = {"ids": "bitcoin", "vs_currencies": "usd"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        data = r.json()
        return float(data["bitcoin"]["usd"])
    except Exception as e:
        print(f"CoinGecko error: {e}")
        return None

def check_signal():
    if len(price_history) < 16:
        return None, 0
    current_price = price_history[-1]
    price_15min_ago = price_history[-16]
    change_pct = ((current_price - price_15min_ago) / price_15min_ago) * 100
    if change_pct >= THRESHOLD:
        return "UP", change_pct
    elif change_pct <= -THRESHOLD:
        return "DOWN", change_pct
    return None, change_pct

def format_signal(direction, price, change):
    trend_emoji = "🟢" if direction == "UP" else "🔴"
    arrow = "⬆️" if direction == "UP" else "⬇️"
    now = datetime.datetime.now().strftime("%H:%M:%S")
    msg = f"{trend_emoji} <b>SIGNAL JELENA - BTC</b> {trend_emoji}\n\n{arrow} Direction : <b>{direction}</b>\n📊 Variation 15min : <b>{change:+.2f}%</b>\n💰 Prix : <b>${price:,.2f}</b>\n🕐 Heure : {now}"
    return msg

def main():
    send_telegram("🤖 <b>Jelena Bot v5 démarré</b>\nSignaux BTC temps réel - 15min window")
    last_signal = None
    last_signal_time = 0
    print("Jelena Bot v5 started")

    while True:
        try:
            now = time.time()
            price = get_btc_price()

            if price is None:
                time.sleep(60)
                continue

            price_history.append(price)
            signal, change = check_signal()

            print(f"{datetime.datetime.now().strftime('%H:%M')} | BTC: ${price:,.0f} | Change 15min: {change:+.2f}% | Signal: {signal}")

            if signal and (now - last_signal_time > 600) and signal != last_signal:
                message = format_signal(signal, price, change)
                send_telegram(message)
                last_signal = signal
                last_signal_time = now
                print(f"Signal sent: {signal}")

            time.sleep(60)

        except KeyboardInterrupt:
            send_telegram("⏹️ Bot arrêté")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
