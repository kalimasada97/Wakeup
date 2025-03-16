import os
import time
import pandas as pd
import numpy as np
from binance.client import Client
from binance.enums import *
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from dotenv import load_dotenv
import telegram

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
TIMEFRAME = "1h"
LEVERAGE = 25
RISK_PERCENT = 0.05  # 5% modal
POSITION_SIZE = 100  # Sesuaikan dengan balance
TP_RATIO = 1.5  # Target Profit 1.5x SL
SL_RATIO = 0.5  # Stop Loss 0.5x TP
FEE = 0.0004  # Binance Fee (Maker/Taker)

# Fungsi Kirim Notifikasi Telegram
def send_telegram(message):
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

# Fungsi Ambil Data Candlestick
def get_klines(symbol, interval, limit=50):
    klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
    df['close'] = df['close'].astype(float)
    return df

# Fungsi Analisis Entry (Menggunakan EMA dan RSI)
def analyze_market():
    df = get_klines(PAIR, TIMEFRAME)
    df['ema50'] = EMAIndicator(df['close'], window=50).ema_indicator()
    df['ema200'] = EMAIndicator(df['close'], window=200).ema_indicator()
    df['rsi'] = RSIIndicator(df['close'], window=14).rsi()

    # Entry Signal: EMA50 > EMA200 & RSI > 55 (Bullish) atau EMA50 < EMA200 & RSI < 45 (Bearish)
    if df['ema50'].iloc[-1] > df['ema200'].iloc[-1] and df['rsi'].iloc[-1] > 55:
        return "LONG"
    elif df['ema50'].iloc[-1] < df['ema200'].iloc[-1] and df['rsi'].iloc[-1] < 45:
        return "SHORT"
    return None

# Fungsi Hitung SL & TP
def calculate_sl_tp(entry_price, position_type):
    if position_type == "LONG":
        sl = entry_price * (1 - SL_RATIO)
        tp = entry_price * (1 + TP_RATIO)
    else:  # SHORT
        sl = entry_price * (1 + SL_RATIO)
        tp = entry_price * (1 - TP_RATIO)
    return round(sl, 2), round(tp, 2)

# Fungsi Eksekusi Order Futures
def place_order(position_type):
    balance = float(client.futures_account_balance()[0]['balance'])
    qty = round((balance * RISK_PERCENT * LEVERAGE) / 100, 3)
    
    if position_type == "LONG":
        order = client.futures_create_order(
            symbol=PAIR, side=SIDE_BUY, type=ORDER_TYPE_MARKET, quantity=qty
        )
    else:
        order = client.futures_create_order(
            symbol=PAIR, side=SIDE_SELL, type=ORDER_TYPE_MARKET, quantity=qty
        )

    entry_price = float(order['fills'][0]['price'])
    sl, tp = calculate_sl_tp(entry_price, position_type)

    # Set TP & SL
    client.futures_create_order(
        symbol=PAIR, side=SIDE_SELL if position_type == "LONG" else SIDE_BUY,
        type=ORDER_TYPE_STOP_MARKET, stopPrice=sl, closePosition=True
    )
    client.futures_create_order(
        symbol=PAIR, side=SIDE_SELL if position_type == "LONG" else SIDE_BUY,
        type=ORDER_TYPE_LIMIT, price=tp, quantity=qty
    )

    # Kirim Jurnal ke Telegram
    send_telegram(f"📊 Trade Executed: {position_type}\n🔹 Entry: {entry_price}\n🔹 SL: {sl}\n🔹 TP: {tp}\n🔹 Size: {qty}")

# Loop Trading Tiap 1 Jam
while True:
    try:
        signal = analyze_market()
        if signal:
            place_order(signal)
        time.sleep(3600)  # 1 jam
    except Exception as e:
        send_telegram(f"⚠️ Error: {str(e)}")
        time.sleep(60)  # Retry dalam 1 menit jika error
