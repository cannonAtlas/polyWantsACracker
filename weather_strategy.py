"""
🦜 Poly Wants A Cracker — Weather Strategy
============================================
Compares weather forecasts from Open-Meteo against Polymarket
odds on weather-related events (temperature records, precipitation, etc.)

Edge comes from: meteorological models are quite accurate 24-48h out,
but prediction markets often lag or misjudge weather events.
"""

import logging
import re
import numpy as np
from typing import Optional
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

import config
from data_feeds import WeatherFeed, find_city_coords

logger = logging.getLogger("polly.weather")


@dataclass
class WeatherSignal:
    """Result of weather analysis for a specific market."""
    market_id: str
    market_question: str
    token_id: str
    our_probability: float
    market_probability: float
    edge: float
    recommended_side: str
    reasoning: str
    forecast_data: dict
    market_type: str  # "temperature", "precipitation", "storm", etc.


class WeatherStrategy:
    """
    Analyzes weather forecasts and compares them to Polymarket odds
    on weather-related markets.
    """

    def __init__(self):
        self.feed = WeatherFeed()

    def analyze_market(self, market: dict, market_probability: float) -> Optional[WeatherSignal]:
        """Analyze a weather market and return a signal if we find edge."""
        question = market.get("question", "")
        description = market.get("description", "")
        full_text = f"{question} {description}"

        # Identify location
        coords = find_city_coords(full_text)
        if coords is None:
            logger.debug(f"Could not identify location for: {question}")
            return None

        lat, lon = coords

        # Classify market type and analyze
        market_type = self._classify_market(full_text)

        if market_type == "temperature":
            return self._analyze_temperature_market(market, market_probability, lat, lon)
        elif market_type == "precipitation":
            return self._analyze_precipitation_market(market, market_probability, lat, lon)
        elif market_type == "snow":
            return self._analyze_snow_market(market, market_probability, lat, lon)
        else:
            logger.debug(f"Unhandled weather market type '{market_type}': {question}")
            return None

    # ── Temperature Markets ──────────────────────────────────

    def _analyze_temperature_market(self, market: dict, market_prob: float,
                                     lat: float, lon: float) -> Optional[WeatherSignal]:
        """Analyze temperature threshold markets (e.g., 'Will NYC hit 90°F?')."""
        question = market.get("question", "")

        # Parse threshold
        temp_f, direction = self._parse_temperature(question)
        if temp_f is None:
            return None

        temp_c = (temp_f - 32) * 5 / 9  # Convert to Celsius for Open-Meteo

        # Get forecast
        forecast = self.feed.get_temperature_forecast(lat, lon, hours_ahead=72)
        if not forecast:
            return None

        # Parse target date from question
        target_date = self._parse_target_date(question)

        # Filter forecast to relevant time window
        if target_date:
            relevant = [
                (t, temp) for t, temp in forecast
                if target_date.strftime("%Y-%m-%d") in t
            ]
        else:
            relevant = forecast[:48]  # Default: next 48 hours

        if not relevant:
            return None

        # Calculate probability from forecast
        temps = [temp for _, temp in relevant]
        max_temp = max(temps)
        min_temp = min(temps)
        avg_temp = np.mean(temps)

        if direction == "above" or direction == "hit":
            # Will temperature exceed threshold?
            if max_temp > temp_c + 2:
                our_prob = 0.90
            elif max_temp > temp_c:
                # Close — use distance-based probability
                margin = (max_temp - temp_c) / 2
                our_prob = 0.5 + min(margin * 0.2, 0.4)
            elif max_temp > temp_c - 2:
                margin = (temp_c - max_temp) / 2
                our_prob = 0.5 - min(margin * 0.2, 0.4)
            else:
                our_prob = 0.10
        else:  # "below"
            if min_temp < temp_c - 2:
                our_prob = 0.90
            elif min_temp < temp_c:
                margin = (temp_c - min_temp) / 2
                our_prob = 0.5 + min(margin * 0.2, 0.4)
            elif min_temp < temp_c + 2:
                margin = (min_temp - temp_c) / 2
                our_prob = 0.5 - min(margin * 0.2, 0.4)
            else:
                our_prob = 0.10

        edge = our_prob - market_prob
        recommended_side = "YES" if edge > 0 else "NO"
        if recommended_side == "NO":
            our_prob = 1 - our_prob
            market_prob = 1 - market_prob
            edge = our_prob - market_prob

        token_ids = self._get_token_ids(market)

        reasoning = (
            f"Temperature market: {question[:80]}. "
            f"Forecast max={max_temp:.1f}°C ({max_temp*9/5+32:.0f}°F), "
            f"min={min_temp:.1f}°C ({min_temp*9/5+32:.0f}°F), "
            f"target={temp_c:.1f}°C ({temp_f:.0f}°F). "
            f"Our prob={our_prob:.3f} vs market={market_prob:.3f} → edge={edge:+.3f}"
        )

        return WeatherSignal(
            market_id=market.get("id", ""),
            market_question=question,
            token_id=token_ids[0] if token_ids else "",
            our_probability=our_prob,
            market_probability=market_prob,
            edge=edge,
            recommended_side=recommended_side,
            reasoning=reasoning,
            forecast_data={"temps": temps, "max": max_temp, "min": min_temp},
            market_type="temperature",
        )

    # ── Precipitation Markets ────────────────────────────────

    def _analyze_precipitation_market(self, market: dict, market_prob: float,
                                       lat: float, lon: float) -> Optional[WeatherSignal]:
        """Analyze rain/precipitation markets."""
        question = market.get("question", "")

        forecast = self.feed.get_precipitation_forecast(lat, lon, hours_ahead=72)
        if not forecast:
            return None

        target_date = self._parse_target_date(question)

        if target_date:
            relevant = [
                f for f in forecast
                if target_date.strftime("%Y-%m-%d") in f["time"]
            ]
        else:
            relevant = forecast[:48]

        if not relevant:
            return None

        # Will it rain? Look at precipitation probability
        max_precip_prob = max(f["probability"] for f in relevant) / 100.0
        total_precip = sum(f["amount_mm"] for f in relevant)
        avg_precip_prob = np.mean([f["probability"] for f in relevant]) / 100.0

        # Parse if market asks about rain amount or just occurrence
        threshold_mm = self._parse_precipitation_threshold(question)

        if threshold_mm:
            # Market asks about specific amount
            if total_precip > threshold_mm * 1.5:
                our_prob = 0.85
            elif total_precip > threshold_mm:
                our_prob = 0.65
            elif total_precip > threshold_mm * 0.5:
                our_prob = 0.35
            else:
                our_prob = 0.15
        else:
            # Market asks "will it rain?"
            our_prob = max_precip_prob * 0.7 + avg_precip_prob * 0.3

        our_prob = float(np.clip(our_prob, 0.05, 0.95))
        edge = our_prob - market_prob
        recommended_side = "YES" if edge > 0 else "NO"
        if recommended_side == "NO":
            our_prob = 1 - our_prob
            market_prob = 1 - market_prob
            edge = our_prob - market_prob

        token_ids = self._get_token_ids(market)

        reasoning = (
            f"Precipitation market: {question[:80]}. "
            f"Forecast: max precip prob={max_precip_prob:.0%}, "
            f"total={total_precip:.1f}mm. "
            f"Our prob={our_prob:.3f} vs market={market_prob:.3f} → edge={edge:+.3f}"
        )

        return WeatherSignal(
            market_id=market.get("id", ""),
            market_question=question,
            token_id=token_ids[0] if token_ids else "",
            our_probability=our_prob,
            market_probability=market_prob,
            edge=edge,
            recommended_side=recommended_side,
            reasoning=reasoning,
            forecast_data={"max_prob": max_precip_prob, "total_mm": total_precip},
            market_type="precipitation",
        )

    # ── Snow Markets ─────────────────────────────────────────

    def _analyze_snow_market(self, market: dict, market_prob: float,
                              lat: float, lon: float) -> Optional[WeatherSignal]:
        """Analyze snowfall markets."""
        question = market.get("question", "")

        forecast = self.feed.get_forecast(lat, lon)
        if not forecast or "hourly" not in forecast:
            return None

        snowfall = forecast["hourly"].get("snowfall", [])
        if not snowfall:
            return None

        target_date = self._parse_target_date(question)
        times = forecast["hourly"].get("time", [])

        if target_date:
            relevant_snow = [
                s for t, s in zip(times, snowfall)
                if target_date.strftime("%Y-%m-%d") in t
            ]
        else:
            relevant_snow = snowfall[:48]

        total_snow_cm = sum(relevant_snow)
        max_hourly = max(relevant_snow) if relevant_snow else 0

        # Parse threshold
        snow_threshold = self._parse_snow_threshold(question)
        if snow_threshold:
            threshold_cm = snow_threshold * 2.54  # inches to cm
            if total_snow_cm > threshold_cm * 1.5:
                our_prob = 0.85
            elif total_snow_cm > threshold_cm:
                our_prob = 0.60
            elif total_snow_cm > threshold_cm * 0.3:
                our_prob = 0.30
            else:
                our_prob = 0.10
        else:
            our_prob = min(0.90, total_snow_cm / 5.0) if total_snow_cm > 0.5 else 0.10

        our_prob = float(np.clip(our_prob, 0.05, 0.95))
        edge = our_prob - market_prob
        recommended_side = "YES" if edge > 0 else "NO"
        if recommended_side == "NO":
            our_prob = 1 - our_prob
            market_prob = 1 - market_prob
            edge = our_prob - market_prob

        token_ids = self._get_token_ids(market)

        reasoning = (
            f"Snow market: {question[:80]}. "
            f"Forecast: {total_snow_cm:.1f}cm total snow. "
            f"Our prob={our_prob:.3f} vs market={market_prob:.3f} → edge={edge:+.3f}"
        )

        return WeatherSignal(
            market_id=market.get("id", ""),
            market_question=question,
            token_id=token_ids[0] if token_ids else "",
            our_probability=our_prob,
            market_probability=market_prob,
            edge=edge,
            recommended_side=recommended_side,
            reasoning=reasoning,
            forecast_data={"total_snow_cm": total_snow_cm},
            market_type="snow",
        )

    # ── Parsing Helpers ──────────────────────────────────────

    @staticmethod
    def _classify_market(text: str) -> str:
        text_lower = text.lower()
        if any(w in text_lower for w in ["temperature", "degrees", "°f", "°c", "hot", "cold", "heat", "freeze"]):
            return "temperature"
        if any(w in text_lower for w in ["rain", "precipitation", "rainfall", "shower"]):
            return "precipitation"
        if any(w in text_lower for w in ["snow", "snowfall", "blizzard", "ice storm"]):
            return "snow"
        if any(w in text_lower for w in ["hurricane", "typhoon", "cyclone"]):
            return "storm"
        if any(w in text_lower for w in ["tornado", "twister"]):
            return "tornado"
        if any(w in text_lower for w in ["wind", "gust"]):
            return "wind"
        return "unknown"

    @staticmethod
    def _parse_temperature(question: str) -> tuple[Optional[float], Optional[str]]:
        """Parse temperature and direction from question."""
        question_lower = question.lower()
        direction = None
        if any(w in question_lower for w in ["above", "over", "exceed", "hit", "reach"]):
            direction = "above"
        elif any(w in question_lower for w in ["below", "under", "drop"]):
            direction = "below"
        if direction is None:
            direction = "hit"

        match = re.search(r'(\d+)\s*°?\s*[fF]', question)
        if match:
            return float(match.group(1)), direction

        match = re.search(r'(\d+)\s*degrees', question_lower)
        if match:
            return float(match.group(1)), direction

        return None, None

    @staticmethod
    def _parse_target_date(question: str) -> Optional[datetime]:
        """Try to extract a target date from the question."""
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
        }
        match = re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2})', question.lower())
        if match:
            month = months[match.group(1)[:3]]
            day = int(match.group(2))
            year = datetime.now().year
            try:
                return datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                pass

        if "tomorrow" in question.lower():
            return datetime.now(timezone.utc) + timedelta(days=1)
        if "today" in question.lower():
            return datetime.now(timezone.utc)

        return None

    @staticmethod
    def _parse_precipitation_threshold(question: str) -> Optional[float]:
        """Parse precipitation threshold in mm."""
        match = re.search(r'([\d.]+)\s*(?:mm|millimeters?)', question.lower())
        if match:
            return float(match.group(1))
        match = re.search(r'([\d.]+)\s*inch', question.lower())
        if match:
            return float(match.group(1)) * 25.4
        return None

    @staticmethod
    def _parse_snow_threshold(question: str) -> Optional[float]:
        """Parse snow threshold in inches."""
        match = re.search(r'([\d.]+)\s*inch', question.lower())
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _get_token_ids(market: dict) -> list:
        """Extract CLOB token IDs from market."""
        import json
        token_ids = market.get("clobTokenIds", "")
        if isinstance(token_ids, str) and token_ids:
            try:
                return json.loads(token_ids)
            except Exception:
                pass
        if isinstance(token_ids, list):
            return token_ids
        return []
