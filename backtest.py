"""
🦜 Poly Wants A Cracker — Backtester
======================================
Historical analysis of strategy edge.
Simulates how our BTC strategy would have performed on past data.

Usage:
    python backtest.py                    # Run with defaults
    python backtest.py --days 7           # Last 7 days
    python backtest.py --threshold 0.03   # Min edge threshold
"""

import argparse
import json
import logging
import os
import sys
import numpy as np
from datetime import datetime, timezone, timedelta

import config
from data_feeds import BTCFeed
from btc_strategy import BTCStrategy
from risk_manager import RiskManager

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("polly.backtest")


class BTCBacktester:
    """
    Backtest the BTC 15-minute strategy using historical klines.

    Approach:
    1. Fetch historical 1-minute klines
    2. For each 15-minute window, simulate a "market" at the window start
    3. Calculate what our strategy would have predicted
    4. Check if the prediction was correct at window end
    5. Track P&L with Kelly sizing
    """

    def __init__(self, initial_bankroll: float = 1000.0,
                 min_edge: float = 0.03):
        self.feed = BTCFeed()
        self.strategy = BTCStrategy()
        self.initial_bankroll = initial_bankroll
        self.min_edge = min_edge

    def run(self, days: int = 3) -> dict:
        """Run backtest over the last N days."""
        logger.info(f"\n🦜 Poly Wants A Cracker — BTC Backtest")
        logger.info(f"{'='*60}")
        logger.info(f"  Period: last {days} days")
        logger.info(f"  Initial bankroll: ${self.initial_bankroll:,.2f}")
        logger.info(f"  Min edge threshold: {self.min_edge:.3f}")
        logger.info(f"  Kelly fraction: {config.KELLY_FRACTION}")
        logger.info(f"{'='*60}\n")

        # Fetch historical data
        # Binance allows up to 1000 candles per request
        total_candles = days * 24 * 60  # 1-min candles
        klines_per_request = 1000

        all_klines = []
        logger.info(f"📥 Fetching {total_candles} 1-min candles...")

        # We'll use what we can get (API limits)
        klines = self.feed.get_klines(interval="1m", limit=min(total_candles, 1000))
        if klines is None or len(klines) < 30:
            logger.error("❌ Could not fetch enough historical data")
            return {}

        logger.info(f"  Got {len(klines)} candles")

        # Simulate 15-minute windows
        closes = klines[:, 4]
        highs = klines[:, 2]
        lows = klines[:, 3]
        volumes = klines[:, 5]
        times = klines[:, 0]

        bankroll = self.initial_bankroll
        trades = []
        wins = 0
        losses = 0
        total_pnl = 0.0

        window_size = 15  # 15-minute windows
        lookback = 50     # Candles needed for indicators

        for i in range(lookback, len(closes) - window_size, window_size):
            # Current state (at window start)
            current_price = closes[i]

            # Simulate target price (use a price level near current)
            # In reality, Polymarket sets specific targets — we simulate
            # by testing above/below current price ± small offset
            for offset_pct in [-0.001, 0.0, 0.001]:
                target_price = current_price * (1 + offset_pct)
                direction = "above" if offset_pct >= 0 else "below"

                # Calculate our indicators using data up to window start
                window_closes = closes[i-lookback:i+1]
                window_highs = highs[i-lookback:i+1]
                window_lows = lows[i-lookback:i+1]
                window_volumes = volumes[i-lookback:i+1]

                rsi = self.strategy._calculate_rsi(window_closes, config.BTC_RSI_PERIOD)
                vwap = self.strategy._calculate_vwap(window_highs, window_lows, window_closes, window_volumes)
                vwap_dev = (current_price - vwap) / vwap if vwap > 0 else 0
                volatility = self.strategy._calculate_volatility(window_closes)
                momentum = self.strategy._calculate_momentum(window_closes)

                # Our probability estimate
                our_prob = self.strategy._estimate_probability(
                    current_price=current_price,
                    target_price=target_price,
                    direction=direction,
                    rsi=rsi,
                    vwap_deviation=vwap_dev,
                    volatility=volatility,
                    momentum=momentum,
                    order_flow=0.0,
                )

                # Simulate a "market" probability (slightly noisy version of true prob)
                # In real life this comes from Polymarket orderbook
                end_price = closes[i + window_size - 1]
                actual_above = end_price > target_price

                # Simulated market prob (assume market is ~efficient with some noise)
                true_prob = 0.5  # Base assumption
                noise = np.random.normal(0, 0.05)
                market_prob = np.clip(true_prob + noise, 0.1, 0.9)

                edge = our_prob - market_prob
                if abs(edge) < self.min_edge:
                    continue

                # Kelly sizing
                kelly_f = RiskManager.kelly_size(our_prob, market_prob)
                if kelly_f <= 0:
                    continue

                bet_size = min(bankroll * kelly_f, bankroll * config.MAX_SINGLE_BET_PCT)
                if bet_size < config.MIN_BET_SIZE_USD:
                    continue

                # Determine outcome
                if direction == "above":
                    bet_on_yes = edge > 0
                    outcome_yes = actual_above
                else:
                    bet_on_yes = edge > 0
                    outcome_yes = not actual_above

                won = (bet_on_yes and outcome_yes) or (not bet_on_yes and not outcome_yes)

                if won:
                    payout = bet_size * (1 / market_prob - 1) if bet_on_yes else bet_size * (1 / (1 - market_prob) - 1)
                    pnl = payout
                    wins += 1
                else:
                    pnl = -bet_size
                    losses += 1

                bankroll += pnl
                total_pnl += pnl

                trades.append({
                    "time_idx": i,
                    "price": current_price,
                    "target": target_price,
                    "direction": direction,
                    "our_prob": our_prob,
                    "market_prob": market_prob,
                    "edge": edge,
                    "kelly": kelly_f,
                    "bet_size": bet_size,
                    "won": won,
                    "pnl": pnl,
                    "bankroll": bankroll,
                    "rsi": rsi,
                })

                if bankroll <= 0:
                    logger.warning("💀 BANKRUPT!")
                    break

            if bankroll <= 0:
                break

        # Results
        results = {
            "total_trades": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / (wins + losses) if (wins + losses) > 0 else 0,
            "total_pnl": total_pnl,
            "final_bankroll": bankroll,
            "return_pct": (bankroll - self.initial_bankroll) / self.initial_bankroll * 100,
            "avg_edge": np.mean([t["edge"] for t in trades]) if trades else 0,
            "avg_kelly": np.mean([t["kelly"] for t in trades]) if trades else 0,
            "max_drawdown": self._calc_max_drawdown(trades),
        }

        self._print_results(results)

        # Save detailed trades
        os.makedirs(config.LOG_DIR, exist_ok=True)
        with open(os.path.join(config.LOG_DIR, "backtest_results.json"), "w") as f:
            json.dump({"results": results, "trades": trades}, f, indent=2)
        logger.info(f"\n📁 Detailed results saved to {config.LOG_DIR}/backtest_results.json")

        return results

    @staticmethod
    def _calc_max_drawdown(trades: list) -> float:
        """Calculate maximum drawdown from trade history."""
        if not trades:
            return 0.0
        bankrolls = [t["bankroll"] for t in trades]
        peak = bankrolls[0]
        max_dd = 0.0
        for b in bankrolls:
            if b > peak:
                peak = b
            dd = (peak - b) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @staticmethod
    def _print_results(results: dict):
        """Print formatted backtest results."""
        logger.info(f"\n{'='*60}")
        logger.info(f"📊 BACKTEST RESULTS")
        logger.info(f"{'='*60}")
        logger.info(f"  Total Trades:    {results['total_trades']}")
        logger.info(f"  Wins:            {results['wins']}")
        logger.info(f"  Losses:          {results['losses']}")
        logger.info(f"  Win Rate:        {results['win_rate']:.1%}")
        logger.info(f"  Total PnL:       ${results['total_pnl']:+,.2f}")
        logger.info(f"  Final Bankroll:  ${results['final_bankroll']:,.2f}")
        logger.info(f"  Return:          {results['return_pct']:+.1f}%")
        logger.info(f"  Avg Edge:        {results['avg_edge']:+.4f}")
        logger.info(f"  Avg Kelly:       {results['avg_kelly']:.4f}")
        logger.info(f"  Max Drawdown:    {results['max_drawdown']:.1%}")
        logger.info(f"{'='*60}")

        if results['win_rate'] > 0.55:
            logger.info("  🦜 SQUAWK! Looking profitable! But past results don't guarantee future crackers!")
        elif results['win_rate'] > 0.45:
            logger.info("  🦜 Meh... roughly break-even. Need more edge!")
        else:
            logger.info("  🦜 Oof... negative edge detected. Time to recalibrate!")


def main():
    parser = argparse.ArgumentParser(description="🦜 Poly Wants A Cracker — Backtester")
    parser.add_argument("--days", type=int, default=3, help="Number of days to backtest")
    parser.add_argument("--threshold", type=float, default=0.03, help="Min edge threshold")
    parser.add_argument("--bankroll", type=float, default=1000.0, help="Starting bankroll")
    args = parser.parse_args()

    bt = BTCBacktester(
        initial_bankroll=args.bankroll,
        min_edge=args.threshold,
    )
    bt.run(days=args.days)


if __name__ == "__main__":
    main()
