"""
🦜 Poly Wants A Cracker — Polymarket Client
=============================================
Wrapper around the Polymarket CLOB API and Gamma markets API.
Handles both read-only operations and authenticated trading.
"""

import logging
import requests
from typing import Optional

import config

logger = logging.getLogger("polly.polymarket")

# Try importing the official client; fall back to REST-only mode
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import (
        OrderArgs, MarketOrderArgs, OrderType, BookParams, OpenOrderParams
    )
    from py_clob_client.order_builder.constants import BUY, SELL
    HAS_CLOB_CLIENT = True
except ImportError:
    HAS_CLOB_CLIENT = False
    logger.warning("py-clob-client not installed — running in REST-only mode")


class PolymarketClient:
    """Unified Polymarket interface: Gamma API for discovery, CLOB for trading."""

    def __init__(self):
        self.gamma_url = config.POLYMARKET_GAMMA_API
        self._clob: Optional[object] = None
        self._authenticated = False

        if HAS_CLOB_CLIENT and config.POLYMARKET_PRIVATE_KEY:
            try:
                self._clob = ClobClient(
                    config.POLYMARKET_HOST,
                    key=config.POLYMARKET_PRIVATE_KEY,
                    chain_id=config.POLYMARKET_CHAIN_ID,
                    signature_type=config.POLYMARKET_SIGNATURE_TYPE,
                    funder=config.POLYMARKET_FUNDER or None,
                )
                self._clob.set_api_creds(self._clob.create_or_derive_api_creds())
                self._authenticated = True
                logger.info("✅ Authenticated with Polymarket CLOB")
            except Exception as e:
                logger.error(f"CLOB auth failed: {e}")
        elif HAS_CLOB_CLIENT:
            self._clob = ClobClient(config.POLYMARKET_HOST)
            logger.info("📖 Read-only CLOB client (no private key)")

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    # ── Gamma Markets API (discovery) ────────────────────────

    def get_markets(self, limit=100, offset=0, active=True, closed=False,
                    category=None, query=None) -> list:
        """Fetch markets from Gamma API with filtering."""
        params = {"limit": limit, "offset": offset, "active": active, "closed": closed}
        if category:
            params["category"] = category
        if query:
            params["slug_contains"] = query
        try:
            resp = requests.get(f"{self.gamma_url}/markets", params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Gamma API error: {e}")
            return []

    def get_events(self, limit=100, active=True, query=None) -> list:
        """Fetch events (groups of markets)."""
        params = {"limit": limit, "active": active}
        if query:
            params["slug_contains"] = query
        try:
            resp = requests.get(f"{self.gamma_url}/events", params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Gamma events error: {e}")
            return []

    def find_btc_markets(self) -> list:
        """Find active BTC 15-minute window markets."""
        markets = []
        for query in ["btc", "bitcoin"]:
            results = self.get_markets(limit=50, query=query)
            for m in results:
                q = (m.get("question", "") + " " + m.get("description", "")).lower()
                if any(kw in q for kw in ["15 min", "15-min", "15min", "minute"]):
                    if m.get("active") and not m.get("closed"):
                        markets.append(m)
        # Deduplicate by id
        seen = set()
        unique = []
        for m in markets:
            if m["id"] not in seen:
                seen.add(m["id"])
                unique.append(m)
        return unique

    def find_weather_markets(self) -> list:
        """Find active weather-related markets."""
        markets = []
        for query in ["weather", "temperature", "hurricane", "rain", "snow", "storm",
                       "heat", "cold", "tornado", "flood", "climate"]:
            results = self.get_markets(limit=50, query=query)
            for m in results:
                if m.get("active") and not m.get("closed"):
                    markets.append(m)
        seen = set()
        unique = []
        for m in markets:
            if m["id"] not in seen:
                seen.add(m["id"])
                unique.append(m)
        return unique

    # ── CLOB API (pricing & trading) ─────────────────────────

    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a token."""
        if not self._clob:
            return None
        try:
            mid = self._clob.get_midpoint(token_id)
            return float(mid) if mid else None
        except Exception as e:
            logger.error(f"Midpoint error: {e}")
            return None

    def get_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        """Get best price for a side."""
        if not self._clob:
            return None
        try:
            price = self._clob.get_price(token_id, side=side)
            return float(price) if price else None
        except Exception as e:
            logger.error(f"Price error: {e}")
            return None

    def get_order_book(self, token_id: str) -> Optional[dict]:
        """Get full order book for a token."""
        if not self._clob:
            return None
        try:
            book = self._clob.get_order_book(token_id)
            return book
        except Exception as e:
            logger.error(f"Order book error: {e}")
            return None

    def get_market_probability(self, market: dict) -> Optional[float]:
        """Extract current YES probability from a market dict."""
        try:
            prices = market.get("outcomePrices", "")
            if isinstance(prices, str) and prices:
                import json
                prices = json.loads(prices)
            if isinstance(prices, list) and len(prices) >= 1:
                return float(prices[0])
        except Exception:
            pass
        # Try via CLOB
        token_ids = market.get("clobTokenIds", "")
        if isinstance(token_ids, str) and token_ids:
            import json
            try:
                token_ids = json.loads(token_ids)
            except Exception:
                return None
        if isinstance(token_ids, list) and len(token_ids) >= 1:
            return self.get_midpoint(token_ids[0])
        return None

    # ── Order Execution ──────────────────────────────────────

    def place_market_order(self, token_id: str, side: str, amount_usd: float) -> dict:
        """Place a market order (Fill-or-Kill)."""
        if not self._authenticated or not HAS_CLOB_CLIENT:
            return {"error": "Not authenticated"}
        try:
            side_const = BUY if side.upper() == "BUY" else SELL
            mo = MarketOrderArgs(
                token_id=token_id,
                amount=amount_usd,
                side=side_const,
                order_type=OrderType.FOK,
            )
            signed = self._clob.create_market_order(mo)
            resp = self._clob.post_order(signed, OrderType.FOK)
            return resp
        except Exception as e:
            logger.error(f"Market order failed: {e}")
            return {"error": str(e)}

    def place_limit_order(self, token_id: str, side: str, price: float,
                          size: float) -> dict:
        """Place a limit order (Good-Til-Cancelled)."""
        if not self._authenticated or not HAS_CLOB_CLIENT:
            return {"error": "Not authenticated"}
        try:
            side_const = BUY if side.upper() == "BUY" else SELL
            order = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side_const,
            )
            signed = self._clob.create_order(order)
            resp = self._clob.post_order(signed, OrderType.GTC)
            return resp
        except Exception as e:
            logger.error(f"Limit order failed: {e}")
            return {"error": str(e)}

    def cancel_all_orders(self) -> dict:
        """Cancel all open orders."""
        if not self._authenticated or not HAS_CLOB_CLIENT:
            return {"error": "Not authenticated"}
        try:
            return self._clob.cancel_all()
        except Exception as e:
            logger.error(f"Cancel all failed: {e}")
            return {"error": str(e)}

    def get_open_orders(self) -> list:
        """Get all open orders."""
        if not self._authenticated or not HAS_CLOB_CLIENT:
            return []
        try:
            return self._clob.get_orders(OpenOrderParams())
        except Exception as e:
            logger.error(f"Get orders failed: {e}")
            return []
