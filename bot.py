import requests
import time
import datetime

TELEGRAM_TOKEN = "8539436833:AAEbwacljaENAab9bkdn2VY7OMoov503GPQ"
CHAT_ID = "8754609023"
COINGECKO_KEY = "CG-4XBTEsUxjpA9RbpgcX8nZRgF"

THRESHOLD = 0.4

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
    params = {"ids": "bitcoin", "vs_currencies": "usd", "include_24hr_change": "true"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        data = r.json()
        return data["bitcoin"]["usd"], data["bitcoin"]["usd_24h_change"]
    except Exception as e:
        print(f"CoinGecko error: {e}")
        return None, None

def get_btc_ohlc():
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc"
    headers = {"x-cg-demo-api-key": COINGECKO_KEY}
    params = {"vs_currency": "usd", "days": "1"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        data = r.json()
        if not data or len(data) < 3:
            return []
        candles = []
        for c in data[-6:]:
            open_price = float(c[1])
            close_price = float(c[4])
            change_pct = ((close_price - open_price) / open_price) * 100
            candles.append({
                "open": open_price,
                "close": close_price,
                "change_pct": change_pct
            })
        return candles
    except Exception as e:
        print(f"CoinGecko OHLC error: {e}")
        return []

def check_signal(candles):
    if len(candles) < 2:
        return None
    current = candles[-2]
    if current["change_pct"] >= THRESHOLD:
        return "UP"
    elif current["change_pct"] <= -THRESHOLD:
        return "DOWN"
    return None

def format_signal(direction, price, change):
    trend_emoji = "🟢" if direction == "UP" else "🔴"
    arrow = "⬆️" if direction == "UP" else "⬇️"
    now = datetime.datetime.now().strftime("%H:%M:%S")
    msg = f"{trend_emoji} <b>SIGNAL JELENA - BTC</b> {trend_emoji}\n\n{arrow} Direction : <b>{direction}</b>\n📊 Variation : <b>{change:+.2f}%</b>\n💰 Prix : <b>${price:,.2f}</b>\n🕐 Heure : {now}"
    return msg

def main():
    send_telegram("🤖 <b>Jelena Bot v4 démarré</b>\nSignaux BTC +/-0.4% - CoinGecko API")
    last_signal = None
    last_signal_time = 0
    print("Jelena Bot v4 started - CoinGecko API")
    while True:
        try:
            now = time.time()
            candles = get_btc_ohlc()
            price, change_24h = get_btc_price()
            if not candles or price is None:
                print("No data, retrying in 60s...")
                time.sleep(60)
                continue
            signal = check_signal(candles)
            current_change = candles[-2]["change_pct"] if len(candles) >= 2 else 0
            print(f"{datetime.datetime.now().strftime('%H:%M')} | BTC: ${price:,.0f} | Change: {current_change:+.2f}% | Signal: {signal}")
            if signal and (now - last_signal_time > 600) and signal != last_signal:
                message = format_signal(signal, price, current_change)
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
