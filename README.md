# 🦜 Poly Wants A Cracker

> A Polymarket trading bot that finds edge on BTC 15-minute window markets and weather prediction markets. Because this parrot doesn't just repeat — it *predicts*.

```
      ___
     (o o)
    /(> <)\
     /|_|\
    (_/ \_)
   SQUAWK! 🦜
```

## What Is This?

Poly Wants A Cracker is an automated trading bot for [Polymarket](https://polymarket.com), the world's largest prediction market. It targets two specific market types where quantitative analysis can provide an edge over the crowd:

1. **BTC 15-Minute Window Markets** — "Will BTC be above $97,500 at 12:15 PM?"
2. **Weather Prediction Markets** — "Will NYC hit 90°F tomorrow?"

The bot only bets when it identifies **positive expected value** — when our calculated probability meaningfully disagrees with the market's price. No edge? No bet. This parrot is patient.

## 🧠 How It Works

### Strategy 1: BTC 15-Minute Windows

Polymarket runs frequent markets on whether BTC will be above or below a specific price at a specific time (usually 15-minute windows). These are essentially ultra-short-term binary options.

**Our edge thesis:** In 15-minute windows, BTC price is heavily influenced by momentum, mean-reversion, and microstructure signals that prediction market participants may not fully price in.

**Indicators used:**

| Indicator | What It Tells Us | Edge Source |
|-----------|-----------------|-------------|
| **RSI** (Relative Strength Index) | Overbought/oversold momentum | Mean-reversion at extremes |
| **VWAP Deviation** | Distance from volume-weighted average | Mean-reversion signal |
| **Volatility Regime** | Trending vs. ranging market | Adjusts probability distribution width |
| **Momentum** | Recent price direction | Short-term trend continuation |
| **Order Flow** | Buy vs. sell pressure imbalance | Real-time directional bias |

**Probability calculation:**
1. Start with a base probability using a normal distribution centered on current price, scaled by recent volatility
2. Adjust up/down based on each indicator's signal
3. Compare our probability vs. Polymarket's implied probability
4. If our probability > market probability + minimum edge threshold → **BET**

### Strategy 2: Weather Odds

Weather forecasts from modern meteorological models (GFS, ECMWF) are remarkably accurate for 24-48 hour predictions. Prediction market participants often rely on vibes, news headlines, or outdated information.

**Our edge thesis:** Free weather APIs provide highly accurate near-term forecasts that often disagree with market pricing.

**Data source:** [Open-Meteo API](https://open-meteo.com/) — free, no API key required, powered by national weather services.

**Market types handled:**
- 🌡️ **Temperature thresholds** — "Will it hit 90°F in NYC?"
- 🌧️ **Precipitation** — "Will it rain in LA tomorrow?"
- ❄️ **Snowfall** — "Will Boston get 6+ inches of snow?"

**How it works:**
1. Parse the market question to identify location, threshold, and timeframe
2. Fetch detailed hourly forecasts from Open-Meteo
3. Calculate probability based on forecast vs. threshold
4. Compare against market pricing
5. Bet when forecast strongly disagrees with market odds

## 💰 Risk Management

The bot uses **Kelly Criterion** for position sizing — the mathematically optimal bet size given our edge and the odds.

### Kelly Criterion

```
f* = (p × b - q) / b

Where:
  p = our estimated probability of winning
  b = net odds offered (payout per $1 bet)
  q = 1 - p (probability of losing)
  f* = fraction of bankroll to bet
```

**Safety measures:**
- **Half-Kelly**: We use 50% of the Kelly-optimal size (less variance, nearly same growth)
- **5% max**: No single bet exceeds 5% of bankroll
- **50% exposure cap**: Total open positions never exceed 50% of bankroll
- **Minimum edge**: Won't bet unless edge > 3% (configurable)
- **Maximum positions**: Caps concurrent open positions at 10

### Paper Trading

**Paper trading is ON by default.** The bot logs all trades with full reasoning without risking real money. Review the logs, validate the edge, then switch to live when confident.

## 🚀 Quick Start

### 1. Install

```bash
cd polywantsacracker
pip install -r requirements.txt
```

### 2. Configure

Create a `.env` file (or set environment variables):

```bash
# Required for live trading (leave empty for paper trading)
POLYMARKET_PRIVATE_KEY=your_private_key_here
POLYMARKET_FUNDER=your_funder_address_here

# Trading mode
PAPER_TRADING=true
INITIAL_BANKROLL=1000.0

# Risk parameters (optional, defaults are sensible)
# KELLY_FRACTION=0.5
# MAX_SINGLE_BET_PCT=0.05
# MIN_EDGE_THRESHOLD=0.03
```

### 3. Run

```bash
# Run both strategies (paper mode)
python bot.py

# BTC strategy only
python bot.py --btc-only

# Weather strategy only
python bot.py --weather-only

# Scan once and exit (good for cron jobs)
python bot.py --scan

# Check portfolio status
python bot.py --status
```

### 4. Backtest

```bash
# Run backtest with defaults
python backtest.py

# Customize
python backtest.py --days 7 --threshold 0.05 --bankroll 5000
```

## 📁 Project Structure

```
polywantsacracker/
├── README.md              # You're reading it! 🦜
├── requirements.txt       # Python dependencies
├── .env                   # Your secrets (create this)
├── config.py              # All settings and risk params
├── polymarket_client.py   # Polymarket API wrapper (CLOB + Gamma)
├── btc_strategy.py        # BTC 15-min window analysis
├── weather_strategy.py    # Weather odds analysis
├── risk_manager.py        # Kelly criterion + bankroll management
├── data_feeds.py          # Binance BTC feed + Open-Meteo weather
├── bot.py                 # Main loop and orchestration
├── backtest.py            # Historical strategy analysis
└── logs/                  # Trade logs, state, backtest results
    ├── trades.jsonl       # Every trade with reasoning
    ├── state.json         # Current positions and bankroll
    └── bot.log            # Runtime logs
```

## 📊 Trade Logging

Every trade is logged to `logs/trades.jsonl` with full context:

```json
{
  "action": "OPEN",
  "timestamp": "2024-01-15T14:30:00Z",
  "position": {
    "market_question": "Will BTC be above $97,500 at 2:15 PM ET?",
    "side": "YES",
    "entry_price": 0.45,
    "size_usd": 25.00,
    "our_probability": 0.62,
    "market_probability": 0.45,
    "edge": 0.17,
    "kelly_fraction": 0.12,
    "reasoning": "BTC @ $97,200 vs target $97,500. RSI=42, VWAP dev=+0.0012, strong upward momentum..."
  }
}
```

## ⚠️ Disclaimers

- **This is experimental software.** Use at your own risk.
- **Paper trading is on by default** for a reason — validate before going live.
- **Past backtest results do not guarantee future performance.**
- Polymarket has geographic restrictions — ensure you're in a permitted jurisdiction.
- The bot's edge depends on market inefficiency which may diminish over time.
- Never risk more than you can afford to lose.

## 🦜 Why "Poly Wants A Cracker"?

Because every good parrot (Polly) wants a treat, and every good trader wants *alpha*. Our Polly searches the Polymarket jungle for mispriced crackers (markets where the crowd is wrong), snatches them up using Kelly-optimal sizing, and squawks triumphantly when they resolve in our favor.

*SQUAWK! 🦜*

---

**Built with 🦜 by a parrot who knows math.**
