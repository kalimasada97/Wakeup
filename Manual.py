import os
import pandas as pd
import numpy as np
from binance.client import Client
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from dotenv import load_dotenv
import telegram
import time
from datetime import datetime, timedelta

# Load API Keys dari .env
load_dotenv()
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Inisialisasi Binance Client & Telegram Bot
client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)

# Konfigurasi Trading
PAIR = "BTCUSDT"
TIMEFRAMES = ["5m", "15m"]  # Analisis di M5 dan M15
LOOKBACK_DAYS = 30  # Analisis 1 bulan ke belakang

# Fungsi Kirim Notifikasi Telegram
def send_telegram(message):
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

# Fungsi Ambil Data Candlestick
def get_klines(symbol, interval, days):
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=days)
    
    klines = client.futures_klines(symbol=symbol, interval=interval, startTime=int(start_time.timestamp() * 1000))
    df = pd.DataFrame(klines, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
    df['time'] = pd.to_datetime(df['time'], unit='ms')
    df['close'] = df['close'].astype(float)
    return df

# Fungsi Analisis Market (Menggunakan EMA & RSI)
def analyze_market(df):
    df['ema50'] = EMAIndicator(df['close'], window=50).ema_indicator()
    df['ema200'] = EMAIndicator(df['close'], window=200).ema_indicator()
    df['rsi'] = RSIIndicator(df['close'], window=14).rsi()

    trades = []

    for i in range(1, len(df)):
        entry_price = df['close'][i]
        position_type = None

        # Entry Signal: EMA50 > EMA200 & RSI > 55 (LONG) atau EMA50 < EMA200 & RSI < 45 (SHORT)
        if df['ema50'][i] > df['ema200'][i] and df['rsi'][i] > 55:
            position_type = "LONG"
        elif df['ema50'][i] < df['ema200'][i] and df['rsi'][i] < 45:
            position_type = "SHORT"

        if position_type:
            sl = entry_price * 0.995 if position_type == "LONG" else entry_price * 1.005
            tp = entry_price * 1.005 if position_type == "LONG" else entry_price * 0.995

            # Simpan trade plan
            trades.append({
                "time": df['time'][i],
                "entry_price": round(entry_price, 2),
                "position": position_type,
                "sl": round(sl, 2),
                "tp": round(tp, 2),
                "result": None  # Akan dihitung di backtest
            })

    return trades

# Fungsi Backtest dan Hitung Winrate
def backtest(trades, df):
    wins, losses = 0, 0

    for trade in trades:
        entry_time = trade["time"]
        entry_price = trade["entry_price"]
        tp, sl = trade["tp"], trade["sl"]
        position = trade["position"]

        # Cari harga setelah entry untuk melihat apakah TP atau SL terkena lebih dulu
        future_data = df[df["time"] > entry_time]

        for _, row in future_data.iterrows():
            if position == "LONG":
                if row["low"] <= sl:
                    trade["result"] = "LOSS"
                    losses += 1
                    break
                elif row["high"] >= tp:
                    trade["result"] = "WIN"
                    wins += 1
                    break
            else:  # SHORT
                if row["high"] >= sl:
                    trade["result"] = "LOSS"
                    losses += 1
                    break
                elif row["low"] <= tp:
                    trade["result"] = "WIN"
                    wins += 1
                    break

    total_trades = wins + losses
    winrate = (wins / total_trades * 100) if total_trades > 0 else 0
    return winrate, total_trades, trades

# Loop Analisis Tiap 1 Jam
while True:
    try:
        report = "📊 **Trade Plan & Backtest Report** 📊\n\n"

        for timeframe in TIMEFRAMES:
            df = get_klines(PAIR, timeframe, LOOKBACK_DAYS)
            trades = analyze_market(df)
            winrate, total_trades, trade_results = backtest(trades, df)

            report += f"⏳ **Timeframe: {timeframe}**\n"
            report += f"📈 **Total Trades:** {total_trades}\n"
            report += f"✅ **Winrate:** {winrate:.2f}%\n\n"

            # Jurnal detail
            for trade in trade_results[:10]:  # Kirim hanya 10 trade pertama ke Telegram
                report += f"📅 {trade['time']}\n"
                report += f"🔹 **Position:** {trade['position']}\n"
                report += f"🔹 **Entry:** {trade['entry_price']}\n"
                report += f"🔹 **SL:** {trade['sl']} | **TP:** {trade['tp']}\n"
                report += f"🎯 **Result:** {trade['result']}\n\n"

        send_telegram(report)
        time.sleep(3600)  # Analisis setiap 1 jam

    except Exception as e:
        send_telegram(f"⚠️ Error: {str(e)}")
        time.sleep(60)  # Retry dalam 1 menit jika error
