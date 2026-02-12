"""
🦜 Poly Wants A Cracker — Risk Manager
========================================
Kelly criterion, bankroll management, and position tracking.
"""

import json
import logging
import os
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional

import config

logger = logging.getLogger("polly.risk")


@dataclass
class Position:
    market_id: str
    market_question: str
    token_id: str
    side: str              # "YES" or "NO"
    entry_price: float
    size_usd: float
    shares: float
    our_probability: float
    market_probability: float
    edge: float
    kelly_fraction: float
    strategy: str          # "btc" or "weather"
    reasoning: str
    timestamp: str = ""
    status: str = "open"   # open, closed, expired

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class RiskManager:
    """
    Manages bankroll, position sizing via Kelly criterion,
    and enforces risk limits.
    """

    def __init__(self, bankroll: float = None):
        self.bankroll = bankroll or config.INITIAL_BANKROLL
        self.positions: list[Position] = []
        self.trade_history: list[dict] = []
        self._load_state()

    # ── Kelly Criterion ──────────────────────────────────────

    @staticmethod
    def kelly_size(our_prob: float, market_prob: float,
                   fraction: float = None) -> float:
        """
        Calculate Kelly criterion bet size as fraction of bankroll.

        Kelly formula for binary outcomes at given odds:
          f* = (p * (1/market_prob - 1) - (1-p)) / (1/market_prob - 1)
             = (p * b - q) / b
        where:
          p = our estimated probability of winning
          b = net odds (payout per $1 bet) = (1/market_prob) - 1
          q = 1 - p

        We use fractional Kelly (half-Kelly by default) for safety.
        """
        if fraction is None:
            fraction = config.KELLY_FRACTION

        if market_prob <= 0 or market_prob >= 1 or our_prob <= 0 or our_prob >= 1:
            return 0.0

        b = (1.0 / market_prob) - 1.0  # net odds
        if b <= 0:
            return 0.0

        p = our_prob
        q = 1.0 - p
        kelly_full = (p * b - q) / b

        if kelly_full <= 0:
            return 0.0  # No edge — don't bet

        return kelly_full * fraction

    # ── Bet Sizing ───────────────────────────────────────────

    def calculate_bet_size(self, our_prob: float, market_prob: float,
                           strategy: str = "") -> tuple[float, float, str]:
        """
        Calculate recommended bet size in USD.
        Returns (bet_size_usd, kelly_fraction, rejection_reason).
        rejection_reason is empty string if bet is approved.
        """
        edge = our_prob - market_prob

        # Check minimum edge
        if edge < config.MIN_EDGE_THRESHOLD:
            return 0.0, 0.0, f"Edge {edge:.3f} below threshold {config.MIN_EDGE_THRESHOLD}"

        # Kelly sizing
        kf = self.kelly_size(our_prob, market_prob)
        if kf <= 0:
            return 0.0, 0.0, "Kelly says don't bet (negative EV)"

        bet_usd = self.bankroll * kf

        # Cap at max single bet
        max_bet = self.bankroll * config.MAX_SINGLE_BET_PCT
        if bet_usd > max_bet:
            bet_usd = max_bet

        # Check min bet
        if bet_usd < config.MIN_BET_SIZE_USD:
            return 0.0, kf, f"Bet size ${bet_usd:.2f} below minimum ${config.MIN_BET_SIZE_USD}"

        # Check open positions
        open_positions = [p for p in self.positions if p.status == "open"]
        if len(open_positions) >= config.MAX_OPEN_POSITIONS:
            return 0.0, kf, f"Max open positions ({config.MAX_OPEN_POSITIONS}) reached"

        # Check total exposure
        total_exposure = sum(p.size_usd for p in open_positions)
        if total_exposure + bet_usd > self.bankroll * 0.5:
            remaining = self.bankroll * 0.5 - total_exposure
            if remaining < config.MIN_BET_SIZE_USD:
                return 0.0, kf, "Total exposure would exceed 50% of bankroll"
            bet_usd = min(bet_usd, remaining)

        return round(bet_usd, 2), kf, ""

    # ── Position Management ──────────────────────────────────

    def open_position(self, market_id: str, market_question: str,
                      token_id: str, side: str, entry_price: float,
                      size_usd: float, our_prob: float, market_prob: float,
                      strategy: str, reasoning: str) -> Position:
        """Record a new position."""
        shares = size_usd / entry_price if entry_price > 0 else 0
        edge = our_prob - market_prob
        kf = self.kelly_size(our_prob, market_prob)

        pos = Position(
            market_id=market_id,
            market_question=market_question,
            token_id=token_id,
            side=side,
            entry_price=entry_price,
            size_usd=size_usd,
            shares=shares,
            our_probability=our_prob,
            market_probability=market_prob,
            edge=edge,
            kelly_fraction=kf,
            strategy=strategy,
            reasoning=reasoning,
        )
        self.positions.append(pos)
        self.bankroll -= size_usd
        self._log_trade("OPEN", pos)
        self._save_state()
        logger.info(f"📈 Opened: {side} on '{market_question[:50]}' — ${size_usd:.2f} @ {entry_price:.4f} (edge: {edge:.3f})")
        return pos

    def close_position(self, position: Position, exit_price: float,
                       pnl: float, reason: str = ""):
        """Close a position and update bankroll."""
        position.status = "closed"
        self.bankroll += position.size_usd + pnl

        record = {
            "action": "CLOSE",
            "reason": reason,
            "exit_price": exit_price,
            "pnl": pnl,
            "position": asdict(position),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.trade_history.append(record)
        self._log_trade("CLOSE", position, extra={"pnl": pnl, "reason": reason})
        self._save_state()
        logger.info(f"📉 Closed: '{position.market_question[:50]}' — PnL: ${pnl:+.2f} ({reason})")

    # ── Stats ────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get portfolio statistics."""
        open_pos = [p for p in self.positions if p.status == "open"]
        closed_pos = [p for p in self.positions if p.status == "closed"]
        total_pnl = sum(t.get("pnl", 0) for t in self.trade_history)
        wins = sum(1 for t in self.trade_history if t.get("pnl", 0) > 0)
        losses = sum(1 for t in self.trade_history if t.get("pnl", 0) <= 0)

        return {
            "bankroll": self.bankroll,
            "open_positions": len(open_pos),
            "total_exposure": sum(p.size_usd for p in open_pos),
            "closed_trades": len(closed_pos),
            "total_pnl": total_pnl,
            "win_rate": wins / (wins + losses) if (wins + losses) > 0 else 0,
            "wins": wins,
            "losses": losses,
        }

    # ── Persistence ──────────────────────────────────────────

    def _save_state(self):
        """Save state to disk."""
        os.makedirs(config.LOG_DIR, exist_ok=True)
        state = {
            "bankroll": self.bankroll,
            "positions": [asdict(p) for p in self.positions],
            "trade_history": self.trade_history,
        }
        state_file = os.path.join(config.LOG_DIR, "state.json")
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)

    def _load_state(self):
        """Load state from disk if exists."""
        state_file = os.path.join(config.LOG_DIR, "state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file) as f:
                    state = json.load(f)
                self.bankroll = state.get("bankroll", self.bankroll)
                self.positions = [Position(**p) for p in state.get("positions", [])]
                self.trade_history = state.get("trade_history", [])
                logger.info(f"📂 Loaded state: bankroll=${self.bankroll:.2f}, {len(self.positions)} positions")
            except Exception as e:
                logger.warning(f"Could not load state: {e}")

    def _log_trade(self, action: str, position: Position, extra: dict = None):
        """Append trade to JSONL log."""
        os.makedirs(config.LOG_DIR, exist_ok=True)
        record = {
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "position": asdict(position),
        }
        if extra:
            record.update(extra)
        with open(config.TRADE_LOG_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
