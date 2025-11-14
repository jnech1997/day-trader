"""Market condition helpers and scheduling utilities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import pandas as pd

from .config import TradingConfig
from .indicators import compute_intraday_indicators


def is_market_choppy(df: pd.DataFrame) -> bool:
    """Detect ranging/choppy conditions - currently unused."""
    return False


def is_trending(df: pd.DataFrame, direction: str) -> bool:
    """Check if market is in a clear trend"""
    if len(df) < 50:
        return False

    last = df.iloc[-1]

    if direction == "long":
        ema_aligned = last["ema_9"] > last["ema_21"] > last["ema_50"]
        price_above = last["close"] > last["ema_9"]
        return ema_aligned and price_above
    else:
        ema_aligned = last["ema_9"] < last["ema_21"] < last["ema_50"]
        price_below = last["close"] < last["ema_9"]
        return ema_aligned and price_below


def check_higher_timeframe_alignment(df_higher: pd.DataFrame, direction: str) -> bool:
    """Confirm signal with higher timeframe trend"""
    if df_higher is None or len(df_higher) < 20:
        return True

    df_higher = compute_intraday_indicators(df_higher)
    last = df_higher.iloc[-1]

    if direction == "long":
        return (
            last["ema_9"] > last["ema_21"]
            and last["close"] > last["ema_9"]
            and last["rsi"] > 50
        )
    else:
        return (
            last["ema_9"] < last["ema_21"]
            and last["close"] < last["ema_9"]
            and last["rsi"] < 50
        )


def is_crypto_prime_time(ts: datetime | None = None) -> bool:
    """
    Best crypto trading hours (overlaps with US market).

    If ts is provided, use that timestamp (for backtests).
    Otherwise, fall back to current UTC time (for live trading).
    """
    if ts is None:
        ts = datetime.now(timezone.utc)

    hour = ts.hour
    # 13:00-21:00 UTC = 9am-5pm ET (most volatile period)
    return 13 <= hour <= 21


def get_current_et_time() -> Tuple[int, int]:
    """Get current hour and minute in ET"""
    now = datetime.now(timezone.utc)
    et_offset = timedelta(hours=-5)
    et_time = now + et_offset
    return et_time.hour, et_time.minute


def is_market_open() -> bool:
    """Check if market is open"""
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    if weekday >= 5:
        return False

    hour, minute = get_current_et_time()
    time_minutes = hour * 60 + minute
    open_minutes = (
        TradingConfig.MARKET_OPEN_HOUR * 60 + TradingConfig.MARKET_OPEN_MINUTE
    )
    close_minutes = (
        TradingConfig.MARKET_CLOSE_HOUR * 60 + TradingConfig.MARKET_CLOSE_MINUTE
    )

    return open_minutes <= time_minutes < close_minutes


def should_force_close() -> bool:
    """Check if we should force close all positions"""
    hour, minute = get_current_et_time()
    time_minutes = hour * 60 + minute
    force_close_minutes = (
        TradingConfig.FORCE_CLOSE_HOUR * 60 + TradingConfig.FORCE_CLOSE_MINUTE
    )

    return time_minutes >= force_close_minutes


def get_active_strategy() -> Optional[str]:
    """Determine which strategy to use based on time of day"""
    hour, minute = get_current_et_time()
    time_minutes = hour * 60 + minute

    for start_h, start_m, end_h, end_m in TradingConfig.MOMENTUM["active_hours"]:
        if start_h * 60 + start_m <= time_minutes < end_h * 60 + end_m:
            return "momentum"

    for start_h, start_m, end_h, end_m in TradingConfig.BREAKOUT["active_hours"]:
        if start_h * 60 + start_m <= time_minutes < end_h * 60 + end_m:
            return "breakout"

    for start_h, start_m, end_h, end_m in TradingConfig.SCALPING["active_hours"]:
        if start_h * 60 + start_m <= time_minutes < end_h * 60 + end_m:
            return "scalping"

    return None


__all__ = [
    "is_market_choppy",
    "is_trending",
    "check_higher_timeframe_alignment",
    "is_crypto_prime_time",
    "get_current_et_time",
    "is_market_open",
    "should_force_close",
    "get_active_strategy",
]
