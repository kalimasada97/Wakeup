import ccxt
import time
import pandas as pd
import numpy as np
import ta  # Library technical analysis
import requests

# ===============================
# KONFIGURASI AWAL
# ===============================
exchange = ccxt.binance({
    'enableRateLimit': True,
})

# Konfigurasi Telegram (Ganti dengan token dan chat ID Anda)
TELEGRAM_BOT_TOKEN = "7747406899:AAGTcw4NK2oYRH27M-PHR1GIc7rpfGKe0EE"     # Ganti dengan token bot Anda
TELEGRAM_CHAT_ID = "5125770095"           # Ganti dengan chat id Telegram Anda

def send_telegram_message(message):
    """Kirim pesan ke Telegram menggunakan Bot API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, data=data)
        if response.status_code != 200:
            print("Gagal mengirim pesan ke Telegram:", response.text)
    except Exception as e:
        print("Error mengirim pesan ke Telegram:", e)

# ===============================
# FUNGSI PENDUKUNG
# ===============================
def get_usdt_pairs():
    """Ambil semua pair dengan akhiran '/USDT' dari Binance."""
    markets = exchange.load_markets()
    usdt_pairs = [symbol for symbol in markets if symbol.endswith('/USDT')]
    return usdt_pairs

def scan_pairs():
    """
    Pindai pair USDT yang memiliki pergerakan minimal 10% dalam satu jam terakhir.
    Menggunakan timeframe 1h dengan mengambil 2 candle (awal dan akhir periode 1h).
    """
    usdt_pairs = get_usdt_pairs()
    qualifying_pairs = []
    for pair in usdt_pairs:
        try:
            ohlcv = exchange.fetch_ohlcv(pair, timeframe='1h', limit=2)
            if len(ohlcv) < 2:
                continue
            open_price = ohlcv[0][1]
            last_price = ohlcv[-1][4]
            change_percent = ((last_price - open_price) / open_price) * 100
            if abs(change_percent) >= 10:
                qualifying_pairs.append((pair, change_percent))
        except Exception as e:
            print(f"Error fetching data for {pair}: {e}")
    return qualifying_pairs

def fetch_ohlcv_dataframe(pair, timeframe='15m', limit=50):
    """
    Ambil data OHLCV dan konversi ke DataFrame.
    Kolom: timestamp, open, high, low, close, volume.
    """
    ohlcv = exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def detect_wave3(df):
    """
    Deteksi struktur wave menggunakan data timeframe 15m.
    Logika sederhana:
      - Wave0: Titik terendah pada 20 candle pertama.
      - Wave1: Titik tertinggi setelah wave0 (pada candle ke-[wave0+1] sampai candle ke-20).
      - Wave2: Koreksi setelah wave1 dalam 10 candle berikutnya.
    Syarat:
      • Koreksi (wave2) tidak boleh melebihi 61.8% dari kenaikan wave1-wave0.
      • Harga saat ini (calon wave3) harus sudah melampaui wave1.
    Jika terpenuhi, kembalikan detail wave.
    """
    try:
        if len(df) < 30:
            return None

        # Tentukan wave0: titik terendah dalam 20 candle pertama
        df_initial = df.iloc[:20]
        wave0_idx = df_initial['close'].idxmin()
        wave0_price = df.loc[wave0_idx, 'close']

        # Cari wave1: titik tertinggi setelah wave0 (dalam candle ke-[wave0+1] hingga candle ke-20)
        df_wave1 = df.loc[wave0_idx+1:20]
        if df_wave1.empty:
            return None
        wave1_idx = df_wave1['close'].idxmax()
        wave1_price = df.loc[wave1_idx, 'close']

        # Cari wave2: koreksi setelah wave1 (dalam 10 candle berikutnya)
        df_wave2 = df.loc[wave1_idx+1:wave1_idx+10]
        if df_wave2.empty:
            return None
        wave2_idx = df_wave2['close'].idxmin()
        wave2_price = df.loc[wave2_idx, 'close']

        # Validasi retracement wave2: (wave1 - wave2) harus kurang dari 61.8% dari (wave1 - wave0)
        total_move = wave1_price - wave0_price
        retracement = (wave1_price - wave2_price) / total_move if total_move != 0 else 0
        if retracement > 0.618:
            return None  # Koreksi terlalu dalam

        # Syarat wave 3: Harga saat ini (candle terakhir) harus lebih tinggi dari wave1
        current_price = df.iloc[-1]['close']
        if current_price <= wave1_price:
            return None

        waves = {
            'wave0_idx': wave0_idx,
            'wave0_price': wave0_price,
            'wave1_idx': wave1_idx,
            'wave1_price': wave1_price,
            'wave2_idx': wave2_idx,
            'wave2_price': wave2_price,
            'current_price': current_price,
            'retracement': retracement,
            'wave3_move': current_price - wave1_price,
        }
        return waves
    except Exception as e:
        print(f"Error in detect_wave3: {e}")
        return None

def analyze_wave3(pair):
    """
    Analisa apakah suatu pair di timeframe 15m menunjukkan pola Wave 3 yang valid.
    Konfirmasi dilakukan dengan:
      - Deteksi pola wave menggunakan fungsi detect_wave3.
      - Candle terakhir harus bullish dengan body > 1%.
      - Konfirmasi volume: volume candle terakhir minimal 50% lebih tinggi dari rata-rata volume sebelumnya.
      - Konfirmasi indikator: 
            • RSI (periode 14) > 50.
            • MACD line di atas signal.
      - Konfirmasi multi-timeframe: data 1h harus mendukung tren naik (candle terakhir bullish).
    Mengembalikan (True, detail) jika valid; jika tidak, (False, {}).
    """
    details = {}
    try:
        # Ambil data 15m selama 50 candle
        df_15m = fetch_ohlcv_dataframe(pair, timeframe='15m', limit=50)
        if df_15m.empty or len(df_15m) < 30:
            return False, {}

        # Deteksi struktur wave
        waves = detect_wave3(df_15m)
        if waves is None:
            return False, {}

        # Konfirmasi candle terakhir pada timeframe 15m
        last_candle = df_15m.iloc[-1]
        open_price = last_candle['open']
        close_price = last_candle['close']
        body_pct = ((close_price - open_price) / open_price) * 100
        if not (close_price > open_price and body_pct > 1):
            return False, {}

        # Konfirmasi volume: volume candle terakhir dibandingkan dengan rata-rata volume (exclude candle terakhir)
        avg_volume = df_15m.iloc[:-1]['volume'].mean()
        volume_last = last_candle['volume']
        if volume_last < avg_volume * 1.5:
            return False, {}

        # Konfirmasi indikator dengan library ta
        df_15m['rsi'] = ta.momentum.rsi(df_15m['close'], window=14)
        rsi_last = df_15m.iloc[-1]['rsi']
        if np.isnan(rsi_last) or rsi_last < 50:
            return False, {}

        # Hitung MACD
        macd_indicator = ta.trend.MACD(df_15m['close'])
        df_15m['macd'] = macd_indicator.macd()
        df_15m['macd_signal'] = macd_indicator.macd_signal()
        macd_last = df_15m.iloc[-1]['macd']
        macd_signal_last = df_15m.iloc[-1]['macd_signal']
        if np.isnan(macd_last) or macd_last < macd_signal_last:
            return False, {}

        # Konfirmasi multi-timeframe: Ambil data timeframe 1h dan cek candle terakhir bullish
        df_1h = fetch_ohlcv_dataframe(pair, timeframe='1h', limit=2)
        if df_1h.empty or len(df_1h) < 2:
            return False, {}
        last_candle_1h = df_1h.iloc[-1]
        if last_candle_1h['close'] <= last_candle_1h['open']:
            return False, {}

        # Kumpulkan detail analisa untuk journaling
        details['pair'] = pair
        details['change_percent_1h'] = round(scan_pairs_dict.get(pair, 0), 2)  # dari hasil scan
        details['15m_wave'] = waves
        details['last_candle_15m'] = {
            'open': open_price,
            'close': close_price,
            'body_pct': round(body_pct, 2),
            'volume': volume_last,
            'avg_volume': round(avg_volume, 2)
        }
        details['RSI'] = round(rsi_last, 2)
        details['MACD'] = round(macd_last, 4)
        details['MACD_signal'] = round(macd_signal_last, 4)
        details['1h_candle'] = {
            'open': last_candle_1h['open'],
            'close': last_candle_1h['close']
        }

        # Bias utama: Karena validitas wave3 terpenuhi dan candle bullish, bias utama adalah *Long Bias*
        details['main_bias'] = "Long Bias"
        details['reasoning'] = (
            "Candle 15m terakhir bullish dengan body >1%, volume meningkat signifikan, "
            "RSI > 50, MACD line di atas signal, dan candle 1h juga mendukung tren naik. "
            "Struktur wave memenuhi kriteria: koreksi tidak melebihi 61.8% dari kenaikan wave, "
            "dan harga saat ini telah melewati wave1."
        )
        return True, details

    except Exception as e:
        print(f"Error analyzing wave3 for {pair}: {e}")
        return False, {}

# Dictionary untuk menyimpan hasil scanning 1h (digunakan untuk journaling)
scan_pairs_dict = {}

# ===============================
# MAIN FUNCTION
# ===============================
def main():
    global scan_pairs_dict
    print("Memindai semua pair USDT di Binance dengan pergerakan >= 10% dalam 1 jam terakhir...")
    qualifying_pairs = scan_pairs()
    scan_pairs_dict = {pair: change for pair, change in qualifying_pairs}
    
    message_scan = "Hasil Scanning Pair USDT (>=10% pergerakan 1h):\n"
    if qualifying_pairs:
        for pair, change in qualifying_pairs:
            message_scan += f" - {pair}: {change:.2f}%\n"
    else:
        message_scan += "Tidak ada pair yang memenuhi kriteria."
    send_telegram_message(message_scan)
    print(message_scan)

    # Analisa masing-masing pair untuk mendeteksi pola Wave 3 di timeframe 15m
    for pair, change in qualifying_pairs:
        analysis_msg = f"\nAnalisa untuk *{pair}*:\nPergerakan 1h: {change:.2f}%\n"
        print(f"\nMenganalisa {pair} untuk mendeteksi pola Wave 3 di TF 15...")
        valid, analysis_details = analyze_wave3(pair)
        if valid:
            analysis_msg += "*Status: TERDETEKSI pola Wave 3 yang valid*\n"
            analysis_msg += f"Main Bias: {analysis_details.get('main_bias')}\n"
            analysis_msg += "\nDetail Analisa:\n"
            wave = analysis_details.get('15m_wave', {})
import ccxt
import time
import pandas as pd
import numpy as np
import ta  # Library technical analysis
import requests

# ===============================
# KONFIGURASI AWAL
# ===============================
exchange = ccxt.binance({
    'enableRateLimit': True,
})

# Konfigurasi Telegram (Ganti dengan token dan chat ID Anda)
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"     # Ganti dengan token bot Anda
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"           # Ganti dengan chat id Telegram Anda

def send_telegram_message(message):
    """Kirim pesan ke Telegram menggunakan Bot API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, data=data)
        if response.status_code != 200:
            print("Gagal mengirim pesan ke Telegram:", response.text)
    except Exception as e:
        print("Error mengirim pesan ke Telegram:", e)

# ===============================
# FUNGSI PENDUKUNG
# ===============================
def get_usdt_pairs():
    """Ambil semua pair dengan akhiran '/USDT' dari Binance."""
    markets = exchange.load_markets()
    usdt_pairs = [symbol for symbol in markets if symbol.endswith('/USDT')]
    return usdt_pairs

def scan_pairs():
    """
    Pindai pair USDT yang memiliki pergerakan minimal 10% dalam satu jam terakhir.
    Menggunakan timeframe 1h dengan mengambil 2 candle (awal dan akhir periode 1h).
    """
    usdt_pairs = get_usdt_pairs()
    qualifying_pairs = []
    for pair in usdt_pairs:
        try:
            ohlcv = exchange.fetch_ohlcv(pair, timeframe='1h', limit=2)
            if len(ohlcv) < 2:
                continue
            open_price = ohlcv[0][1]
            last_price = ohlcv[-1][4]
            change_percent = ((last_price - open_price) / open_price) * 100
            if abs(change_percent) >= 10:
                qualifying_pairs.append((pair, change_percent))
        except Exception as e:
            print(f"Error fetching data for {pair}: {e}")
    return qualifying_pairs

def fetch_ohlcv_dataframe(pair, timeframe='15m', limit=50):
    """
    Ambil data OHLCV dan konversi ke DataFrame.
    Kolom: timestamp, open, high, low, close, volume.
    """
    ohlcv = exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def detect_wave3(df):
    """
    Deteksi struktur wave menggunakan data timeframe 15m.
    Logika sederhana:
      - Wave0: Titik terendah pada 20 candle pertama.
      - Wave1: Titik tertinggi setelah wave0 (pada candle ke-[wave0+1] sampai candle ke-20).
      - Wave2: Koreksi setelah wave1 dalam 10 candle berikutnya.
    Syarat:
      • Koreksi (wave2) tidak boleh melebihi 61.8% dari kenaikan wave1-wave0.
      • Harga saat ini (calon wave3) harus sudah melampaui wave1.
    Jika terpenuhi, kembalikan detail wave.
    """
    try:
        if len(df) < 30:
            return None

        # Tentukan wave0: titik terendah dalam 20 candle pertama
        df_initial = df.iloc[:20]
        wave0_idx = df_initial['close'].idxmin()
        wave0_price = df.loc[wave0_idx, 'close']

        # Cari wave1: titik tertinggi setelah wave0 (dalam candle ke-[wave0+1] hingga candle ke-20)
        df_wave1 = df.loc[wave0_idx+1:20]
        if df_wave1.empty:
            return None
        wave1_idx = df_wave1['close'].idxmax()
        wave1_price = df.loc[wave1_idx, 'close']

        # Cari wave2: koreksi setelah wave1 (dalam 10 candle berikutnya)
        df_wave2 = df.loc[wave1_idx+1:wave1_idx+10]
        if df_wave2.empty:
            return None
        wave2_idx = df_wave2['close'].idxmin()
        wave2_price = df.loc[wave2_idx, 'close']

        # Validasi retracement wave2: (wave1 - wave2) harus kurang dari 61.8% dari (wave1 - wave0)
        total_move = wave1_price - wave0_price
        retracement = (wave1_price - wave2_price) / total_move if total_move != 0 else 0
        if retracement > 0.618:
            return None  # Koreksi terlalu dalam

        # Syarat wave 3: Harga saat ini (candle terakhir) harus lebih tinggi dari wave1
        current_price = df.iloc[-1]['close']
        if current_price <= wave1_price:
            return None

        waves = {
            'wave0_idx': wave0_idx,
            'wave0_price': wave0_price,
            'wave1_idx': wave1_idx,
            'wave1_price': wave1_price,
            'wave2_idx': wave2_idx,
            'wave2_price': wave2_price,
            'current_price': current_price,
            'retracement': retracement,
            'wave3_move': current_price - wave1_price,
        }
        return waves
    except Exception as e:
        print(f"Error in detect_wave3: {e}")
        return None

def analyze_wave3(pair):
    """
    Analisa apakah suatu pair di timeframe 15m menunjukkan pola Wave 3 yang valid.
    Konfirmasi dilakukan dengan:
      - Deteksi pola wave menggunakan fungsi detect_wave3.
      - Candle terakhir harus bullish dengan body > 1%.
      - Konfirmasi volume: volume candle terakhir minimal 50% lebih tinggi dari rata-rata volume sebelumnya.
      - Konfirmasi indikator: 
            • RSI (periode 14) > 50.
            • MACD line di atas signal.
      - Konfirmasi multi-timeframe: data 1h harus mendukung tren naik (candle terakhir bullish).
    Mengembalikan (True, detail) jika valid; jika tidak, (False, {}).
    """
    details = {}
    try:
        # Ambil data 15m selama 50 candle
        df_15m = fetch_ohlcv_dataframe(pair, timeframe='15m', limit=50)
        if df_15m.empty or len(df_15m) < 30:
            return False, {}

        # Deteksi struktur wave
        waves = detect_wave3(df_15m)
        if waves is None:
            return False, {}

        # Konfirmasi candle terakhir pada timeframe 15m
        last_candle = df_15m.iloc[-1]
        open_price = last_candle['open']
        close_price = last_candle['close']
        body_pct = ((close_price - open_price) / open_price) * 100
        if not (close_price > open_price and body_pct > 1):
            return False, {}

        # Konfirmasi volume: volume candle terakhir dibandingkan dengan rata-rata volume (exclude candle terakhir)
        avg_volume = df_15m.iloc[:-1]['volume'].mean()
        volume_last = last_candle['volume']
        if volume_last < avg_volume * 1.5:
            return False, {}

        # Konfirmasi indikator dengan library ta
        df_15m['rsi'] = ta.momentum.rsi(df_15m['close'], window=14)
        rsi_last = df_15m.iloc[-1]['rsi']
        if np.isnan(rsi_last) or rsi_last < 50:
            return False, {}

        # Hitung MACD
        macd_indicator = ta.trend.MACD(df_15m['close'])
        df_15m['macd'] = macd_indicator.macd()
        df_15m['macd_signal'] = macd_indicator.macd_signal()
        macd_last = df_15m.iloc[-1]['macd']
        macd_signal_last = df_15m.iloc[-1]['macd_signal']
        if np.isnan(macd_last) or macd_last < macd_signal_last:
            return False, {}

        # Konfirmasi multi-timeframe: Ambil data timeframe 1h dan cek candle terakhir bullish
        df_1h = fetch_ohlcv_dataframe(pair, timeframe='1h', limit=2)
        if df_1h.empty or len(df_1h) < 2:
            return False, {}
        last_candle_1h = df_1h.iloc[-1]
        if last_candle_1h['close'] <= last_candle_1h['open']:
            return False, {}

        # Kumpulkan detail analisa untuk journaling
        details['pair'] = pair
        details['change_percent_1h'] = round(scan_pairs_dict.get(pair, 0), 2)  # dari hasil scan
        details['15m_wave'] = waves
        details['last_candle_15m'] = {
            'open': open_price,
            'close': close_price,
            'body_pct': round(body_pct, 2),
            'volume': volume_last,
            'avg_volume': round(avg_volume, 2)
        }
        details['RSI'] = round(rsi_last, 2)
        details['MACD'] = round(macd_last, 4)
        details['MACD_signal'] = round(macd_signal_last, 4)
        details['1h_candle'] = {
            'open': last_candle_1h['open'],
            'close': last_candle_1h['close']
        }

        # Bias utama: Karena validitas wave3 terpenuhi dan candle bullish, bias utama adalah *Long Bias*
        details['main_bias'] = "Long Bias"
        details['reasoning'] = (
            "Candle 15m terakhir bullish dengan body >1%, volume meningkat signifikan, "
            "RSI > 50, MACD line di atas signal, dan candle 1h juga mendukung tren naik. "
            "Struktur wave memenuhi kriteria: koreksi tidak melebihi 61.8% dari kenaikan wave, "
            "dan harga saat ini telah melewati wave1."
        )
        return True, details

    except Exception as e:
        print(f"Error analyzing wave3 for {pair}: {e}")
        return False, {}

# Dictionary untuk menyimpan hasil scanning 1h (digunakan untuk journaling)
scan_pairs_dict = {}

# ===============================
# MAIN FUNCTION
# ===============================
def main():
    global scan_pairs_dict
    print("Memindai semua pair USDT di Binance dengan pergerakan >= 10% dalam 1 jam terakhir...")
    qualifying_pairs = scan_pairs()
    scan_pairs_dict = {pair: change for pair, change in qualifying_pairs}
    
    message_scan = "Hasil Scanning Pair USDT (>=10% pergerakan 1h):\n"
    if qualifying_pairs:
        for pair, change in qualifying_pairs:
            message_scan += f" - {pair}: {change:.2f}%\n"
    else:
        message_scan += "Tidak ada pair yang memenuhi kriteria."
    send_telegram_message(message_scan)
    print(message_scan)

    # Analisa masing-masing pair untuk mendeteksi pola Wave 3 di timeframe 15m
    for pair, change in qualifying_pairs:
        analysis_msg = f"\nAnalisa untuk *{pair}*:\nPergerakan 1h: {change:.2f}%\n"
        print(f"\nMenganalisa {pair} untuk mendeteksi pola Wave 3 di TF 15...")
        valid, analysis_details = analyze_wave3(pair)
        if valid:
            analysis_msg += "*Status: TERDETEKSI pola Wave 3 yang valid*\n"
            analysis_msg += f"Main Bias: {analysis_details.get('main_bias')}\n"
            analysis_msg += "\nDetail Analisa:\n"
            wave = analysis_details.get('15m_wave', {})
            analysis_msg += (
                f" - Wave0: {wave.get('wave0_price'):.4f}\n"
                f" - Wave1: {wave.get('wave1_price'):.4f}\n"
                f" - Wave2: {wave.get('wave2_price'):.4f}\n"
                f" - Retracement: {wave.get('retracement')*100:.2f}%\n"
                f" - Wave3 Move: {wave.get('wave3_move'):.4f}\n"
            )
            lc = analysis_details.get('last_candle_15m', {})
            analysis_msg += (
                f" - Candle 15m terakhir: Open: {lc.get('open')}, Close: {lc.get('close')}, Body: {lc.get('body_pct')}%\n"
                f" - Volume: {lc.get('volume')} (Avg: {lc.get('avg_volume')})\n"
            )
            analysis_msg += (
                f" - RSI: {analysis_details.get('RSI')}\n"
                f" - MACD: {analysis_details.get('MACD')} | Signal: {analysis_details.get('MACD_signal')}\n"
            )
            tf1h = analysis_details.get('1h_candle', {})
            analysis_msg += f" - Candle 1h: Open: {tf1h.get('open')}, Close: {tf1h.get('close')}\n"
            analysis_msg += f"\n*Reasoning:*\n{analysis_details.get('reasoning')}\n"
        else:
            analysis_msg += "*Status: Tidak memenuhi kriteria Wave 3.*\n"
        send_telegram_message(analysis_msg)
        print(analysis_msg)
        # Delay sebelum analisa pair berikutnya
        time.sleep(5)

if __name__ == "__main__":
    main()
