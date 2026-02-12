"""
🦜 Poly Wants A Cracker — Data Feeds
======================================
BTC price data from Binance. Weather data from Open-Meteo.
"""

import logging
import requests
import numpy as np
from datetime import datetime, timezone
from typing import Optional

import config

logger = logging.getLogger("polly.feeds")


# ═══════════════════════════════════════════════════════════════
#  BTC Price Feed (Binance public API — no key needed)
# ═══════════════════════════════════════════════════════════════

class BTCFeed:
    """Fetch BTC/USDT data from Binance public API."""

    def __init__(self):
        self.base_url = config.BINANCE_API_URL

    def get_current_price(self) -> Optional[float]:
        """Get current BTC/USDT price."""
        try:
            resp = requests.get(
                f"{self.base_url}/ticker/price",
                params={"symbol": "BTCUSDT"},
                timeout=10,
            )
            resp.raise_for_status()
            return float(resp.json()["price"])
        except Exception as e:
            logger.error(f"BTC price fetch error: {e}")
            return None

    def get_klines(self, interval: str = "1m", limit: int = 100) -> Optional[np.ndarray]:
        """
        Fetch OHLCV klines. Returns numpy array with columns:
        [open_time, open, high, low, close, volume, close_time,
         quote_volume, trades, taker_buy_base, taker_buy_quote, ignore]
        """
        try:
            resp = requests.get(
                f"{self.base_url}/klines",
                params={"symbol": "BTCUSDT", "interval": interval, "limit": limit},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return np.array(data, dtype=float)
        except Exception as e:
            logger.error(f"BTC klines error: {e}")
            return None

    def get_ticker_24h(self) -> Optional[dict]:
        """Get 24h ticker stats."""
        try:
            resp = requests.get(
                f"{self.base_url}/ticker/24hr",
                params={"symbol": "BTCUSDT"},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"BTC 24h ticker error: {e}")
            return None

    def get_recent_trades(self, limit: int = 100) -> Optional[list]:
        """Get recent trades for order flow analysis."""
        try:
            resp = requests.get(
                f"{self.base_url}/trades",
                params={"symbol": "BTCUSDT", "limit": limit},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"BTC trades error: {e}")
            return None


# ═══════════════════════════════════════════════════════════════
#  Weather Feed (Open-Meteo — free, no API key)
# ═══════════════════════════════════════════════════════════════

class WeatherFeed:
    """Fetch weather forecasts from Open-Meteo API."""

    def __init__(self):
        self.base_url = config.OPEN_METEO_API_URL

    def get_forecast(self, latitude: float, longitude: float,
                     hourly_vars: list = None) -> Optional[dict]:
        """
        Get weather forecast for a location.
        Default hourly variables: temperature, precipitation, wind, humidity.
        """
        if hourly_vars is None:
            hourly_vars = [
                "temperature_2m",
                "precipitation_probability",
                "precipitation",
                "windspeed_10m",
                "relative_humidity_2m",
                "snowfall",
                "weathercode",
            ]
        try:
            resp = requests.get(
                f"{self.base_url}/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "hourly": ",".join(hourly_vars),
                    "forecast_days": 3,
                    "timezone": "UTC",
                },
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Weather forecast error: {e}")
            return None

    def get_temperature_forecast(self, latitude: float, longitude: float,
                                  hours_ahead: int = 48) -> Optional[list]:
        """Get temperature forecast as list of (time, temp_celsius) tuples."""
        data = self.get_forecast(latitude, longitude, ["temperature_2m"])
        if not data or "hourly" not in data:
            return None
        times = data["hourly"].get("time", [])[:hours_ahead]
        temps = data["hourly"].get("temperature_2m", [])[:hours_ahead]
        return list(zip(times, temps))

    def get_precipitation_forecast(self, latitude: float, longitude: float,
                                    hours_ahead: int = 48) -> Optional[list]:
        """Get precipitation probability forecast."""
        data = self.get_forecast(
            latitude, longitude,
            ["precipitation_probability", "precipitation"]
        )
        if not data or "hourly" not in data:
            return None
        times = data["hourly"].get("time", [])[:hours_ahead]
        probs = data["hourly"].get("precipitation_probability", [])[:hours_ahead]
        amounts = data["hourly"].get("precipitation", [])[:hours_ahead]
        return [
            {"time": t, "probability": p, "amount_mm": a}
            for t, p, a in zip(times, probs, amounts)
        ]


# ═══════════════════════════════════════════════════════════════
#  Common city coordinates for weather markets
# ═══════════════════════════════════════════════════════════════

CITY_COORDS = {
    "new york": (40.7128, -74.0060),
    "nyc": (40.7128, -74.0060),
    "los angeles": (34.0522, -118.2437),
    "la": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298),
    "miami": (25.7617, -80.1918),
    "houston": (29.7604, -95.3698),
    "phoenix": (33.4484, -112.0740),
    "denver": (39.7392, -104.9903),
    "seattle": (47.6062, -122.3321),
    "boston": (42.3601, -71.0589),
    "atlanta": (33.7490, -84.3880),
    "washington dc": (38.9072, -77.0369),
    "dc": (38.9072, -77.0369),
    "san francisco": (37.7749, -122.4194),
    "sf": (37.7749, -122.4194),
    "dallas": (32.7767, -96.7970),
    "london": (51.5074, -0.1278),
    "paris": (48.8566, 2.3522),
    "tokyo": (35.6762, 139.6503),
}


def find_city_coords(text: str) -> Optional[tuple]:
    """Try to extract city coordinates from market text."""
    text_lower = text.lower()
    for city, coords in CITY_COORDS.items():
        if city in text_lower:
            return coords
    return None
