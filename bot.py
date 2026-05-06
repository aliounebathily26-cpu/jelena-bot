import requests
import time
import datetime

TELEGRAM_TOKEN = "8539436833:AAEbwacljaENAab9bkdn2VY7OMoov503GPQ"
CHAT_ID = "8754609023"

MIN_CANDLES = 3
MAX_TRADES = 3
STOP_AFTER_LOSSES = 2

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_btc_candles(interval="15m", limit=10):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": "BTCUSDT", "interval": interval, "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        candles = []
        for c in data:
            open_price = float(c[1])
            close_price = float(c[4])
            high = float(c[2])
            low = float(c[3])
            body_size = abs(close_price - open_price)
            total_range = high - low
            candles.append({
                "open": open_price,
                "close": close_price,
                "high": high,
                "low": low,
                "green": close_price > open_price,
                "body_size": body_size,
                "total_range": total_range,
                "body_ratio": body_size / total_range if total_range > 0 else 0
            })
        return candles
    except Exception as e:
        print(f"Binance error: {e}")
        return []

def get_trend(candles_h1, candles_h4):
    if not candles_h1 or not candles_h4:
        return None
    h1_greens = sum(1 for c in candles_h1[-5:] if c["green"])
    h4_greens = sum(1 for c in candles_h4[-3:] if c["green"])
    if h1_greens >= 3 and h4_greens >= 2:
        return "UP"
    elif h1_greens <= 2 and h4_greens <= 1:
        return "DOWN"
    return None

def check_signal(candles_15m, trend):
    if len(candles_15m) < MIN_CANDLES + 1:
        return None
    last_candles = candles_15m[-(MIN_CANDLES+1):-1]
    all_green = all(c["green"] for c in last_candles)
    all_red = all(not c["green"] for c in last_candles)
    if not all_green and not all_red:
        return None
    for c in last_candles:
        if c["body_ratio"] < 0.3:
            return None
    direction = "UP" if all_green else "DOWN"
    if trend and direction != trend:
        return None
    return direction

def format_signal(direction, candles_15m):
    current_price = candles_15m[-1]["close"]
    trend_emoji = "🟢" if direction == "UP" else "🔴"
    arrow = "⬆️" if direction == "UP" else "⬇️"
    now = datetime.datetime.now().strftime("%H:%M:%S")
    msg = f"{trend_emoji} <b>SIGNAL JELENA - BTC</b> {trend_emoji}\n\n{arrow} Direction : <b>{direction}</b>\n💰 Prix : <b>${current_price:,.2f}</b>\n🕐 Heure : {now}\n\n✅ 3+ bougies consécutives\n✅ Bougies fortes\n✅ Aligné tendance H1/H4\n\n⚠️ Max 20% du capital"
    return msg

def main():
    send_telegram("🤖 <b>Jelena Bot démarré</b>\nSurveillance BTC 15min active...")
    trades_today = 0
    consecutive_losses = 0
    last_signal = None
    last_signal_time = 0
    session_active = True
    print("Bot started.")
    while True:
        try:
            now = time.time()
            current_hour = datetime.datetime.now().hour
            if current_hour == 0 and datetime.datetime.now().minute == 0:
                trades_today = 0
                consecutive_losses = 0
                session_active = True
            if not session_active:
                time.sleep(60)
                continue
            if trades_today >= MAX_TRADES:
                time.sleep(60)
                continue
            if consecutive_losses >= STOP_AFTER_LOSSES:
                if session_active:
                    send_telegram("🛑 <b>2 pertes d'affilée - Session arrêtée</b>")
                    session_active = False
                time.sleep(60)
                continue
            candles_15m = get_btc_candles("15m", 10)
            candles_h1 = get_btc_candles("1h", 6)
            candles_h4 = get_btc_candles("4h", 4)
            if not candles_15m:
                time.sleep(30)
                continue
            trend = get_trend(candles_h1, candles_h4)
            signal = check_signal(candles_15m, trend)
            if signal and (now - last_signal_time > 900) and signal != last_signal:
                message = format_signal(signal, candles_15m)
                send_telegram(message)
                last_signal = signal
                last_signal_time = now
                trades_today += 1
                print(f"Signal: {signal} | Trades: {trades_today}")
            time.sleep(60)
        except KeyboardInterrupt:
            send_telegram("⏹️ Bot arrêté")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
