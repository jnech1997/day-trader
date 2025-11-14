"""Indicator calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Volume Weighted Average Price"""
    df = df.copy()
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap"] = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()
    df["vwap"] = df["vwap"].fillna(df["close"])
    return df


def compute_intraday_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute day trading indicators"""
    df = df.copy()

    # RSI
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-10)
    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi"] = df["rsi"].fillna(50)

    # EMAs
    df["ema_9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()

    # Volume
    df["volume_ma"] = df["volume"].rolling(window=20).mean()
    df["vol_ratio"] = df["volume"] / (df["volume_ma"] + 1)
    df["vol_ratio"] = df["vol_ratio"].fillna(1.0)

    # ATR
    high_low = df["high"] - df["low"]
    high_close = np.abs(df["high"] - df["close"].shift())
    low_close = np.abs(df["low"] - df["close"].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    df["atr"] = ranges.max(axis=1).rolling(14).mean()
    df["atr"] = df["atr"].fillna(df["close"] * 0.02)

    # ATR floor
    atr_floor = df["close"] * 0.01
    df["atr"] = df["atr"].clip(lower=atr_floor)

    # Momentum
    df["momentum"] = df["close"].pct_change(periods=10) * 100
    df["momentum"] = df["momentum"].fillna(0)

    # Support/Resistance
    df["resistance"] = df["high"].rolling(window=20).max()
    df["support"] = df["low"].rolling(window=20).min()

    return df


def normalize_df(df: pd.DataFrame) -> pd.DataFrame | None:
    """Normalize DataFrame format"""
    if df is None or df.empty:
        return None

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    if "timestamp" not in df.columns:
        df = df.reset_index()
        first_col = df.columns[0].lower()
        if first_col in ["date", "datetime", "timestamp"]:
            df.rename(columns={df.columns[0]: "timestamp"}, inplace=True)
        else:
            df["timestamp"] = df.index

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])

    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            df[col] = 0.0

    df["volume"] = df["volume"].replace([None, np.nan], 0).astype(float).clip(lower=0)
    df = df.sort_values("timestamp")
    df = df.drop_duplicates(subset=["timestamp"])
    df = df.reset_index(drop=True)

    return df


__all__ = [
    "compute_vwap",
    "compute_intraday_indicators",
    "normalize_df",
]
