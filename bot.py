import requests
import time
import datetime

TELEGRAM_TOKEN = "8539436833:AAEbwacljaENAab9bkdn2VY7OMoov503GPQ"
CHAT_ID = "8754609023"

THRESHOLD = 0.4

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_btc_candles(interval="15", limit=8):
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "spot", "symbol": "BTCUSDT", "interval": interval, "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get("retCode") != 0:
            return []
        candles = []
        for c in data["result"]["list"]:
            open_price = float(c[1])
            high = float(c[2])
            low = float(c[3])
            close_price = float(c[4])
            volume = float(c[5])
            candles.append({
                "open": open_price,
                "close": close_price,
                "high": high,
                "low": low,
                "volume": volume,
                "change_pct": ((close_price - open_price) / open_price) * 100
            })
        candles.reverse()
        return candles
    except Exception as e:
        print(f"Bybit error: {e}")
        return []

def check_signal(candles):
    if len(candles) < 6:
        return None
    current = candles[-2]
    avg_volume = sum(c["volume"] for c in candles[-6:-1]) / 5
    if current["volume"] < avg_volume * 0.8:
        return None
    if current["change_pct"] >= THRESHOLD:
        return "UP"
    elif current["change_pct"] <= -THRESHOLD:
        return "DOWN"
    return None

def format_signal(direction, candles):
    current_price = candles[-1]["close"]
    change = candles[-2]["change_pct"]
    trend_emoji = "🟢" if direction == "UP" else "🔴"
    arrow = "⬆️" if direction == "UP" else "⬇️"
    now = datetime.datetime.now().strftime("%H:%M:%S")
    msg = f"{trend_emoji} <b>SIGNAL JELENA - BTC</b> {trend_emoji}\n\n{arrow} Direction : <b>{direction}</b>\n📊 Variation : <b>{change:+.2f}%</b>\n💰 Prix : <b>${current_price:,.2f}</b>\n🕐 Heure : {now}"
    return msg

def main():
    send_telegram("🤖 <b>Jelena Bot v3 démarré</b>\nSignaux BTC +/-0.4% sur 15min...")
    last_signal = None
    last_signal_time = 0
    print("Jelena Bot v3 started")
    while True:
        try:
            now = time.time()
            candles = get_btc_candles("15", 8)
            if not candles:
                time.sleep(30)
                continue
            signal = check_signal(candles)
            print(f"{datetime.datetime.now().strftime('%H:%M')} | BTC: ${candles[-1]['close']:,.0f} | Change: {candles[-2]['change_pct']:+.2f}% | Signal: {signal}")
            if signal and (now - last_signal_time > 600) and signal != last_signal:
                message = format_signal(signal, candles)
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
            time.sleep(30)

if __name__ == "__main__":
    main()
