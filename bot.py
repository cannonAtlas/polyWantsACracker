"""
🦜 Poly Wants A Cracker — Main Bot
====================================
The main event loop that scans markets, runs strategies,
and executes trades when edge is found.

      ___
     (o o)
    /(> <)\\
     /|_|\\
    (_/ \\_)
   SQUAWK! 🦜

Usage:
    python bot.py                    # Run both strategies
    python bot.py --btc-only         # BTC strategy only
    python bot.py --weather-only     # Weather strategy only
    python bot.py --scan             # Scan once and exit
    python bot.py --status           # Show portfolio status
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import config
from polymarket_client import PolymarketClient
from btc_strategy import BTCStrategy
from weather_strategy import WeatherStrategy
from risk_manager import RiskManager

# ── Logging Setup ────────────────────────────────────────────

os.makedirs(config.LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.BOT_LOG_FILE),
    ],
)
logger = logging.getLogger("polly")


BANNER = """
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   🦜  P O L Y   W A N T S   A   C R A C K E R  🦜       ║
║                                                           ║
║   Polymarket Trading Bot — Finding Edge Since 2024        ║
║                                                           ║
║   Mode: {mode:<47s} ║
║   Bankroll: ${bankroll:<44s} ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
"""


class PollyBot:
    """Main bot orchestrator."""

    def __init__(self):
        self.client = PolymarketClient()
        self.risk = RiskManager()
        self.btc_strategy = BTCStrategy()
        self.weather_strategy = WeatherStrategy()

    def run(self, btc: bool = True, weather: bool = True, scan_once: bool = False):
        """Main loop: scan markets and execute trades."""
        mode = "PAPER" if config.PAPER_TRADING else "LIVE"
        if not btc:
            mode += " (weather only)"
        elif not weather:
            mode += " (BTC only)"

        print(BANNER.format(
            mode=mode,
            bankroll=f"{self.risk.bankroll:,.2f}",
        ))

        if not config.PAPER_TRADING and not self.client.is_authenticated:
            logger.error("❌ Live trading requires authentication! Set POLYMARKET_PRIVATE_KEY.")
            logger.info("💡 Running in paper mode instead.")

        cycle = 0
        while True:
            cycle += 1
            logger.info(f"{'='*60}")
            logger.info(f"🔄 Scan cycle #{cycle} — {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

            try:
                if btc:
                    self._run_btc_scan()

                if weather:
                    self._run_weather_scan()

                self._print_status()

            except KeyboardInterrupt:
                logger.info("🛑 Shutting down gracefully...")
                break
            except Exception as e:
                logger.error(f"💥 Error in scan cycle: {e}", exc_info=True)

            if scan_once:
                break

            # Sleep until next scan
            interval = min(
                config.BTC_SCAN_INTERVAL_SECONDS if btc else 9999,
                config.WEATHER_SCAN_INTERVAL_SECONDS if weather else 9999,
            )
            logger.info(f"💤 Next scan in {interval}s...")
            time.sleep(interval)

    def _run_btc_scan(self):
        """Scan BTC 15-minute markets for edge."""
        logger.info("₿ Scanning BTC 15-min markets...")
        markets = self.client.find_btc_markets()
        logger.info(f"  Found {len(markets)} active BTC markets")

        for market in markets:
            try:
                market_prob = self.client.get_market_probability(market)
                if market_prob is None:
                    continue

                signal = self.btc_strategy.analyze_market(market, market_prob)
                if signal is None:
                    continue

                logger.info(f"  📊 {signal.market_question[:60]}")
                logger.info(f"     Edge: {signal.edge:+.3f} | Our: {signal.our_probability:.3f} | Market: {signal.market_probability:.3f}")

                if abs(signal.edge) >= config.MIN_EDGE_THRESHOLD:
                    self._execute_signal(signal, "btc")
                else:
                    logger.debug(f"     ⏭️ Edge too small, skipping")

            except Exception as e:
                logger.error(f"  Error analyzing BTC market: {e}")

    def _run_weather_scan(self):
        """Scan weather markets for edge."""
        logger.info("🌤️ Scanning weather markets...")
        markets = self.client.find_weather_markets()
        logger.info(f"  Found {len(markets)} active weather markets")

        for market in markets:
            try:
                market_prob = self.client.get_market_probability(market)
                if market_prob is None:
                    continue

                signal = self.weather_strategy.analyze_market(market, market_prob)
                if signal is None:
                    continue

                logger.info(f"  🌡️ {signal.market_question[:60]}")
                logger.info(f"     Edge: {signal.edge:+.3f} | Our: {signal.our_probability:.3f} | Market: {signal.market_probability:.3f}")

                if abs(signal.edge) >= config.MIN_EDGE_THRESHOLD:
                    self._execute_signal(signal, "weather")
                else:
                    logger.debug(f"     ⏭️ Edge too small, skipping")

            except Exception as e:
                logger.error(f"  Error analyzing weather market: {e}")

    def _execute_signal(self, signal, strategy: str):
        """Execute a trade based on a signal (paper or live)."""
        market_prob = signal.market_probability
        our_prob = signal.our_probability

        bet_size, kelly_f, rejection = self.risk.calculate_bet_size(our_prob, market_prob, strategy)

        if rejection:
            logger.info(f"     🚫 Rejected: {rejection}")
            return

        side = signal.recommended_side
        entry_price = market_prob  # Approximate

        logger.info(f"     ✅ SIGNAL: {side} ${bet_size:.2f} (Kelly={kelly_f:.3f}, edge={signal.edge:+.3f})")
        logger.info(f"     📝 {signal.reasoning}")

        if config.PAPER_TRADING:
            # Paper trade — just record it
            self.risk.open_position(
                market_id=signal.market_id,
                market_question=signal.market_question,
                token_id=signal.token_id,
                side=side,
                entry_price=entry_price,
                size_usd=bet_size,
                our_prob=our_prob,
                market_prob=market_prob,
                strategy=strategy,
                reasoning=signal.reasoning,
            )
            logger.info(f"     📄 Paper trade recorded")
        else:
            # Live trade
            if not signal.token_id:
                logger.error("     ❌ No token ID — cannot place order")
                return

            result = self.client.place_market_order(
                token_id=signal.token_id,
                side="BUY" if side == "YES" else "SELL",
                amount_usd=bet_size,
            )

            if "error" in result:
                logger.error(f"     ❌ Order failed: {result['error']}")
            else:
                self.risk.open_position(
                    market_id=signal.market_id,
                    market_question=signal.market_question,
                    token_id=signal.token_id,
                    side=side,
                    entry_price=entry_price,
                    size_usd=bet_size,
                    our_prob=our_prob,
                    market_prob=market_prob,
                    strategy=strategy,
                    reasoning=signal.reasoning,
                )
                logger.info(f"     💰 LIVE order placed: {result}")

    def _print_status(self):
        """Print current portfolio status."""
        stats = self.risk.get_stats()
        logger.info(f"  📊 Portfolio: bankroll=${stats['bankroll']:,.2f} | "
                     f"open={stats['open_positions']} | "
                     f"exposure=${stats['total_exposure']:,.2f} | "
                     f"PnL=${stats['total_pnl']:+,.2f} | "
                     f"W/L={stats['wins']}/{stats['losses']}")

    def show_status(self):
        """Display detailed portfolio status."""
        stats = self.risk.get_stats()
        print("\n🦜 Poly Wants A Cracker — Portfolio Status\n")
        print(f"  💰 Bankroll:      ${stats['bankroll']:,.2f}")
        print(f"  📈 Open Positions: {stats['open_positions']}")
        print(f"  💸 Total Exposure: ${stats['total_exposure']:,.2f}")
        print(f"  📊 Total PnL:     ${stats['total_pnl']:+,.2f}")
        print(f"  ✅ Wins:           {stats['wins']}")
        print(f"  ❌ Losses:         {stats['losses']}")
        print(f"  📈 Win Rate:       {stats['win_rate']:.1%}")

        open_pos = [p for p in self.risk.positions if p.status == "open"]
        if open_pos:
            print(f"\n  Open Positions:")
            for p in open_pos:
                print(f"    • {p.side} '{p.market_question[:50]}' — ${p.size_usd:.2f} @ {p.entry_price:.4f} (edge: {p.edge:+.3f})")
        print()


def main():
    parser = argparse.ArgumentParser(description="🦜 Poly Wants A Cracker — Polymarket Trading Bot")
    parser.add_argument("--btc-only", action="store_true", help="Run BTC strategy only")
    parser.add_argument("--weather-only", action="store_true", help="Run weather strategy only")
    parser.add_argument("--scan", action="store_true", help="Scan once and exit")
    parser.add_argument("--status", action="store_true", help="Show portfolio status")
    args = parser.parse_args()

    bot = PollyBot()

    if args.status:
        bot.show_status()
        return

    btc = not args.weather_only
    weather = not args.btc_only

    bot.run(btc=btc, weather=weather, scan_once=args.scan)


if __name__ == "__main__":
    main()
