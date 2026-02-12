"""
🦜 Poly Wants A Cracker — BTC 15-Minute Window Strategy
=========================================================
Analyzes BTC momentum to find edge on Polymarket's
"Will BTC be above/below $X in the next 15 minutes?" markets.

Indicators used:
  - RSI (Relative Strength Index) — momentum oscillator
  - VWAP deviation — mean-reversion signal
  - Volatility regime — trending vs ranging
  - Order flow imbalance — buy/sell pressure
"""

import logging
import re
import numpy as np
from typing import Optional
from dataclasses import dataclass

import config
from data_feeds import BTCFeed

logger = logging.getLogger("polly.btc")


@dataclass
class BTCSignal:
    """Result of BTC analysis for a specific market."""
    market_id: str
    market_question: str
    token_id: str
    target_price: float
    direction: str          # "above" or "below"
    current_price: float
    our_probability: float
    market_probability: float
    edge: float
    recommended_side: str   # "YES" or "NO"
    reasoning: str
    components: dict        # Individual indicator readings


class BTCStrategy:
    """
    Analyzes BTC price action to estimate probability of
    BTC being above/below a target price in a 15-min window.
    """

    def __init__(self):
        self.feed = BTCFeed()

    def analyze_market(self, market: dict, market_probability: float) -> Optional[BTCSignal]:
        """
        Analyze a single BTC 15-min market and return a signal if we find edge.
        """
        # Parse target price and direction from market question
        question = market.get("question", "")
        target_price, direction = self._parse_btc_market(question)
        if target_price is None:
            logger.debug(f"Could not parse BTC market: {question}")
            return None

        # Fetch current data
        current_price = self.feed.get_current_price()
        if current_price is None:
            return None

        klines = self.feed.get_klines(interval=config.BTC_CANDLE_INTERVAL, limit=100)
        if klines is None or len(klines) < 20:
            return None

        # Calculate indicators
        closes = klines[:, 4]   # close prices
        highs = klines[:, 2]
        lows = klines[:, 3]
        volumes = klines[:, 5]

        rsi = self._calculate_rsi(closes, config.BTC_RSI_PERIOD)
        vwap = self._calculate_vwap(highs, lows, closes, volumes)
        vwap_deviation = (current_price - vwap) / vwap if vwap > 0 else 0
        volatility = self._calculate_volatility(closes)
        momentum = self._calculate_momentum(closes)

        # Order flow analysis
        trades = self.feed.get_recent_trades(limit=200)
        order_flow = self._analyze_order_flow(trades) if trades else 0.0

        # Calculate our probability
        our_prob = self._estimate_probability(
            current_price=current_price,
            target_price=target_price,
            direction=direction,
            rsi=rsi,
            vwap_deviation=vwap_deviation,
            volatility=volatility,
            momentum=momentum,
            order_flow=order_flow,
        )

        edge = our_prob - market_probability

        # Determine recommended side
        if edge > 0:
            recommended_side = "YES"
        elif (1 - our_prob) - (1 - market_probability) > config.MIN_EDGE_THRESHOLD:
            recommended_side = "NO"
            our_prob = 1 - our_prob
            market_probability = 1 - market_probability
            edge = our_prob - market_probability
        else:
            recommended_side = "YES"

        # Get token ID
        token_ids = market.get("clobTokenIds", "")
        if isinstance(token_ids, str):
            import json
            try:
                token_ids = json.loads(token_ids)
            except Exception:
                token_ids = []
        token_id = token_ids[0] if token_ids else ""

        components = {
            "rsi": rsi,
            "vwap_deviation": vwap_deviation,
            "volatility": volatility,
            "momentum": momentum,
            "order_flow": order_flow,
        }

        reasoning = (
            f"BTC @ ${current_price:,.0f} vs target ${target_price:,.0f} ({direction}). "
            f"RSI={rsi:.1f}, VWAP dev={vwap_deviation:+.4f}, "
            f"Vol={volatility:.4f}, Mom={momentum:+.4f}, "
            f"OrderFlow={order_flow:+.3f}. "
            f"Our prob={our_prob:.3f} vs market={market_probability:.3f} → edge={edge:+.3f}"
        )

        return BTCSignal(
            market_id=market.get("id", ""),
            market_question=question,
            token_id=token_id,
            target_price=target_price,
            direction=direction,
            current_price=current_price,
            our_probability=our_prob,
            market_probability=market_probability,
            edge=edge,
            recommended_side=recommended_side,
            reasoning=reasoning,
            components=components,
        )

    # ── Probability Estimation ───────────────────────────────

    def _estimate_probability(self, current_price: float, target_price: float,
                               direction: str, rsi: float, vwap_deviation: float,
                               volatility: float, momentum: float,
                               order_flow: float) -> float:
        """
        Estimate probability that BTC will be above/below target in ~15 min.

        Approach: Start with a base probability from price distance,
        then adjust using technical indicators.
        """
        # Price distance as fraction
        distance = (target_price - current_price) / current_price

        # Base probability: how likely to cross the target
        # Using a simple normal distribution assumption
        # 15-min expected move ≈ volatility * sqrt(15)
        expected_move = volatility * np.sqrt(15)
        if expected_move < 0.0001:
            expected_move = 0.0001

        if direction == "above":
            # P(price > target) = P(move > distance)
            z_score = distance / expected_move
            from scipy.stats import norm
            try:
                base_prob = 1 - norm.cdf(z_score)
            except ImportError:
                # Fallback: sigmoid approximation
                base_prob = 1.0 / (1.0 + np.exp(z_score * 2))
        else:  # "below"
            z_score = -distance / expected_move
            try:
                from scipy.stats import norm
                base_prob = 1 - norm.cdf(z_score)
            except ImportError:
                base_prob = 1.0 / (1.0 + np.exp(z_score * 2))

        # ── Adjustments ──────────────────────────────────────

        adjustment = 0.0

        # RSI adjustment: oversold = likely to bounce up, overbought = likely to drop
        if rsi < config.BTC_RSI_OVERSOLD:
            # Oversold → more likely to go UP
            rsi_adj = 0.05 * (config.BTC_RSI_OVERSOLD - rsi) / config.BTC_RSI_OVERSOLD
            adjustment += rsi_adj if direction == "above" else -rsi_adj
        elif rsi > config.BTC_RSI_OVERBOUGHT:
            # Overbought → more likely to go DOWN
            rsi_adj = 0.05 * (rsi - config.BTC_RSI_OVERBOUGHT) / (100 - config.BTC_RSI_OVERBOUGHT)
            adjustment += -rsi_adj if direction == "above" else rsi_adj

        # VWAP deviation: price far from VWAP tends to revert
        if abs(vwap_deviation) > 0.001:
            vwap_adj = -vwap_deviation * 0.5  # Mean reversion
            adjustment += vwap_adj if direction == "above" else -vwap_adj

        # Momentum: recent trend continuation
        mom_adj = momentum * 10  # Scale momentum signal
        adjustment += mom_adj if direction == "above" else -mom_adj

        # Order flow: buy/sell pressure
        flow_adj = order_flow * 0.03
        adjustment += flow_adj if direction == "above" else -flow_adj

        # Apply adjustment with bounds
        our_prob = np.clip(base_prob + adjustment, 0.02, 0.98)

        return float(our_prob)

    # ── Technical Indicators ─────────────────────────────────

    @staticmethod
    def _calculate_rsi(closes: np.ndarray, period: int = 14) -> float:
        """Calculate RSI (Relative Strength Index)."""
        if len(closes) < period + 1:
            return 50.0  # neutral

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def _calculate_vwap(highs: np.ndarray, lows: np.ndarray,
                        closes: np.ndarray, volumes: np.ndarray) -> float:
        """Calculate Volume Weighted Average Price."""
        typical_price = (highs + lows + closes) / 3.0
        # Use last 60 candles for VWAP
        n = min(60, len(typical_price))
        tp = typical_price[-n:]
        vol = volumes[-n:]
        total_vol = np.sum(vol)
        if total_vol == 0:
            return closes[-1]
        return float(np.sum(tp * vol) / total_vol)

    @staticmethod
    def _calculate_volatility(closes: np.ndarray, lookback: int = 20) -> float:
        """Calculate recent volatility as std of returns."""
        if len(closes) < lookback + 1:
            lookback = len(closes) - 1
        if lookback < 2:
            return 0.001
        returns = np.diff(np.log(closes[-lookback-1:]))
        return float(np.std(returns))

    @staticmethod
    def _calculate_momentum(closes: np.ndarray, lookback: int = 10) -> float:
        """Calculate price momentum (rate of change)."""
        if len(closes) < lookback + 1:
            return 0.0
        return float((closes[-1] - closes[-lookback-1]) / closes[-lookback-1])

    @staticmethod
    def _analyze_order_flow(trades: list) -> float:
        """
        Analyze recent trades for buy/sell imbalance.
        Returns value from -1 (all sells) to +1 (all buys).
        """
        if not trades:
            return 0.0
        buy_volume = 0.0
        sell_volume = 0.0
        for t in trades:
            qty = float(t.get("qty", 0))
            if t.get("isBuyerMaker", False):
                sell_volume += qty  # Buyer is maker = seller is taker
            else:
                buy_volume += qty
        total = buy_volume + sell_volume
        if total == 0:
            return 0.0
        return (buy_volume - sell_volume) / total

    # ── Market Parsing ───────────────────────────────────────

    @staticmethod
    def _parse_btc_market(question: str) -> tuple[Optional[float], Optional[str]]:
        """
        Parse a BTC market question to extract target price and direction.
        Examples:
          "Will BTC be above $97,500 at 12:15 PM ET?" → (97500, "above")
          "Bitcoin below $96,000 on Feb 10?" → (96000, "below")
        """
        question_lower = question.lower()

        # Determine direction
        direction = None
        if "above" in question_lower or "over" in question_lower:
            direction = "above"
        elif "below" in question_lower or "under" in question_lower:
            direction = "below"

        if direction is None:
            return None, None

        # Extract price (handles $97,500 or $97500 formats)
        price_match = re.search(r'\$?([\d,]+(?:\.\d+)?)', question)
        if price_match:
            price_str = price_match.group(1).replace(",", "")
            try:
                target_price = float(price_str)
                if target_price > 1000:  # Sanity check — BTC price
                    return target_price, direction
            except ValueError:
                pass

        return None, None
