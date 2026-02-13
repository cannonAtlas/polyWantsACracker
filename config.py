"""
🦜 Poly Wants A Cracker — Configuration
========================================
All settings, API keys, and risk parameters live here.
Load from environment variables or .env file.
"""

import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # env vars work fine without dotenv

# ─── Polymarket ───────────────────────────────────────────────
POLYMARKET_HOST = "https://clob.polymarket.com"
POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"
POLYMARKET_CHAIN_ID = 137  # Polygon

# Auth (leave empty for paper trading / read-only)
POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY", "")
POLYMARKET_FUNDER = os.getenv("POLYMARKET_FUNDER", "")
POLYMARKET_SIGNATURE_TYPE = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "0"))

# ─── Trading Mode ─────────────────────────────────────────────
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"
INITIAL_BANKROLL = float(os.getenv("INITIAL_BANKROLL", "1000.0"))  # USD

# ─── Risk Parameters ──────────────────────────────────────────
KELLY_FRACTION = 0.5          # Half-Kelly for safety
MAX_SINGLE_BET_PCT = 0.05     # Never risk >5% of bankroll on one market
MIN_EDGE_THRESHOLD = 0.03     # Minimum edge (our_prob - market_prob) to bet
MAX_OPEN_POSITIONS = 10       # Max concurrent positions
MIN_BET_SIZE_USD = 1.0        # Minimum bet size

# ─── BTC Strategy ─────────────────────────────────────────────
BTC_RSI_PERIOD = 14
BTC_RSI_OVERSOLD = 30
BTC_RSI_OVERBOUGHT = 70
BTC_VWAP_LOOKBACK_MINUTES = 60
BTC_VOLATILITY_LOOKBACK = 20  # candles
BTC_CANDLE_INTERVAL = "1m"    # 1-minute candles from Binance
BTC_SCAN_INTERVAL_SECONDS = 30

# ─── Weather Strategy ─────────────────────────────────────────
WEATHER_SCAN_INTERVAL_SECONDS = 300  # 5 min
WEATHER_MIN_CONFIDENCE = 0.7  # Minimum forecast confidence to consider

# ─── Data Feeds ───────────────────────────────────────────────
BINANCE_API_URL = "https://api.binance.com/api/v3"
OPEN_METEO_API_URL = "https://api.open-meteo.com/v1"

# ─── Logging ──────────────────────────────────────────────────
LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
TRADE_LOG_FILE = os.path.join(LOG_DIR, "trades.jsonl")
BOT_LOG_FILE = os.path.join(LOG_DIR, "bot.log")
