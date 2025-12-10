"""Strategy signal definitions."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .config import TradingConfig
from .market import check_higher_timeframe_alignment, is_crypto_prime_time, is_trending
from .settings import logger


class ScalpingSignals:
    """Scalping logic - CRYPTO MOMENTUM OPTIMIZED"""

    @staticmethod
    def check_signal(
        df: pd.DataFrame,
        config: dict,
        is_crypto: bool = False,
        verbose: bool = False,
        symbol: str | None = None,
    ) -> Optional[str]:
        if df is None or len(df) < 60:
            return None

        df = df.copy()
        last = df.iloc[-1]

        # Basic ATR sanity
        atr = float(last.get("atr", 0.0))
        price = float(last["close"])

        if not np.isfinite(atr) or atr <= 0:
            return None

        atr_floor = price * (0.0075 if is_crypto else 0.002)
        if atr < atr_floor:
            atr = atr_floor

        rsi = float(last["rsi"])
        rsi_min = float(config.get("rsi_min", 40))
        rsi_max = float(config.get("rsi_max", 80))
        enable_shorts = bool(config.get("enable_shorts", True))

        if is_crypto:
            if not symbol:
                symbol = "CRYPTO"
            symbol = symbol.upper()

            bar_ts = last.get("timestamp")
            if isinstance(bar_ts, pd.Timestamp):
                bar_ts = bar_ts.to_pydatetime()

            if not is_crypto_prime_time(bar_ts):
                return None

            volume = float(last["volume"])
            vol_usd = volume * price

            min_required_usd = TradingConfig.CRYPTO_MIN_VOL.get(symbol, 0)

            recent = df.tail(120)
            vol_ma = float(recent["volume"].mean() or 0.0)
            vol_ma_usd = vol_ma * price if vol_ma > 0 else price
            vol_surge = vol_usd / max(vol_ma_usd, 1.0)

            if vol_usd < min_required_usd:
                return None

            min_surge = 1.3
            if vol_surge < min_surge:
                if verbose:
                    logger.info(
                        f"[CRYPTO VOL SURGE] {symbol}: "
                        f"vol_usd={vol_usd:.0f}, surge={vol_surge:.2f}x < {min_surge:.1f}x"
                    )
                return None

            if vol_surge > 10.0:
                if verbose:
                    logger.info(
                        f"[CRYPTO BLOWOFF] {symbol}: vol_surge={vol_surge:.1f}x, skipping"
                    )
                return None

            ema9 = float(last["ema_9"])
            ema21 = float(last["ema_21"])
            ema50 = float(last["ema_50"])
            vwap = float(last["vwap"])

            up_trend = ema9 > ema21 > ema50

            price_above_ema9 = price > ema9
            o = float(last["open"])
            momentum_ok = price > o

            rsi_min_eff = max(rsi_min, 50.0)
            rsi_max_eff = min(rsi_max, 75.0)

            if rsi > 72.0:
                if verbose:
                    logger.info(
                        f"[CRYPTO RSI EXTENDED] {symbol}: RSI={rsi:.1f} > 72, skipping"
                    )
                return None

            rsi_ok = rsi_min_eff < rsi < rsi_max_eff

            dist = abs(price - ema9)
            if dist > 2.0 * atr:
                if verbose:
                    logger.info(
                        f"[CRYPTO EXTENDED] {symbol}: "
                        f"|price-EMA9|={dist:.2f} > 2.0×ATR"
                    )
                return None

            h = float(last["high"])
            l = float(last["low"])
            range_hl = max(h - l, 1e-9)
            close_pos = (price - l) / range_hl

            if close_pos < 0.7:
                return None

            recent_high = float(recent["high"].max())
            if recent_high > 0 and price > recent_high * 0.9975:
                if verbose:
                    logger.info(
                        f"[CRYPTO LOCAL HIGH] {symbol}: "
                        f"price={price:.2f} ~ recent_high={recent_high:.2f}, skipping"
                    )
                return None

            long_ok = (
                up_trend
                and price_above_ema9
                and momentum_ok
                and rsi_ok
                and price > vwap
                and close_pos > 0.7
            )

            if long_ok:
                if verbose:
                    logger.info(
                        f"✅ Scalping LONG (CRYPTO) {symbol}: "
                        f"Close={price:.2f}, RSI={rsi:.1f}, ATR={atr:.2f}"
                    )
                return "long"

            return None

        # Stocks branch
        ema9 = float(last["ema_9"])
        ema21 = float(last["ema_21"])
        ema50 = float(last["ema_50"])
        vwap = float(last["vwap"])

        if rsi > rsi_max or rsi < rsi_min:
            if verbose:
                logger.info(
                    f"[SCALP FILTER] RSI out of bounds: {rsi:.1f} not in {rsi_min}-{rsi_max}"
                )
            return None

        dist_from_ema21 = abs(price - ema21)
        if dist_from_ema21 > atr * 1.0:
            if verbose:
                logger.info(
                    f"[SCALP FILTER] |price-EMA21|={dist_from_ema21:.2f} > 1.0×ATR={atr:.2f}"
                )
            return None

        up_trend = ema9 > ema21 > ema50
        down_trend = ema9 < ema21 < ema50

        long_ok = up_trend and price > ema9 and price > vwap and rsi_min < rsi < rsi_max

        short_ok = (
            enable_shorts
            and down_trend
            and price < ema9
            and price < vwap
            and (100 - rsi_max) < rsi < (100 - rsi_min)
        )

        if long_ok:
            if verbose:
                logger.info(
                    f"✅ Scalping LONG (STOCK) "
                    f"{symbol or 'STOCK'}: Close={price:.2f}, RSI={rsi:.1f}, ATR={atr:.2f}"
                )
            return "long"

        if short_ok:
            if verbose:
                logger.info(
                    f"✅ Scalping SHORT (STOCK) "
                    f"{symbol or 'STOCK'}: Close={price:.2f}, RSI={rsi:.1f}, ATR={atr:.2f}"
                )
            return "short"

        return None


class MomentumSignals:
    """Momentum on 15min charts"""

    @staticmethod
    def check_signal(
        df: pd.DataFrame,
        df_higher: pd.DataFrame,
        config: dict,
        is_crypto: bool = False,
        verbose=False,
        symbol: str | None = None,
    ) -> Optional[str]:
        if len(df) < 50:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]

        min_vol = (
            config["min_volume_usd_crypto"] if is_crypto else config["min_volume_stock"]
        )
        if last["volume"] < min_vol:
            return None

        if (
            last["close"] > last["ema_9"]
            and prev["close"] <= prev["ema_9"]
            and last["close"] > last["vwap"]
            and config["rsi_min"] < last["rsi"] < config["rsi_max"]
        ):
            if config.get("require_trend_alignment", False):
                if not is_trending(df, "long"):
                    if verbose:
                        logger.debug("Momentum LONG rejected - no uptrend")
                    return None
                if df_higher is not None and not check_higher_timeframe_alignment(
                    df_higher, "long"
                ):
                    if verbose:
                        logger.debug("Momentum LONG rejected - higher TF not aligned")
                    return None

            if verbose:
                name = symbol or ("CRYPTO" if is_crypto else "STOCK")
                logger.info(
                    f"✅ Momentum LONG {name}: "
                    f"Price={last['close']:.2f}, RSI={last['rsi']:.1f}"
                )
            return "long"

        if (
            last["close"] < last["ema_9"]
            and prev["close"] >= prev["ema_9"]
            and last["close"] < last["vwap"]
            and (100 - config["rsi_max"]) < last["rsi"] < (100 - config["rsi_min"])
        ):
            if config.get("require_trend_alignment", False):
                if not is_trending(df, "short"):
                    if verbose:
                        logger.debug("Momentum SHORT rejected - no downtrend")
                    return None
                if df_higher is not None and not check_higher_timeframe_alignment(
                    df_higher, "short"
                ):
                    if verbose:
                        logger.debug("Momentum SHORT rejected - higher TF not aligned")
                    return None

            if verbose:
                name = symbol or ("CRYPTO" if is_crypto else "STOCK")
                logger.info(
                    f"✅ Momentum SHORT {name}: "
                    f"Price={last['close']:.2f}, RSI={last['rsi']:.1f}"
                )
            return "short"

        return None


class BreakoutSignals:
    """Breakout on 1H charts"""

    @staticmethod
    def check_signal(
        df: pd.DataFrame,
        config: dict,
        is_crypto: bool = False,
        verbose=False,
        symbol: str | None = None,
    ) -> Optional[str]:
        if len(df) < 50:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]

        min_vol = (
            config["min_volume_usd_crypto"] if is_crypto else config["min_volume_stock"]
        )
        if last["volume"] < min_vol:
            return None

        if (
            last["close"] > last["resistance"] * config["breakout_threshold"]
            and prev["close"] <= prev["resistance"]
            and last["close"] > last["vwap"]
            and last["rsi"] > 50
        ):
            if verbose:
                name = symbol or ("CRYPTO" if is_crypto else "STOCK")
                logger.info(
                    f"✅ Breakout LONG {name}: "
                    f"Price={last['close']:.2f}, Resistance={last['resistance']:.2f}"
                )
            return "long"

        if (
            last["close"] < last["support"] * (2 - config["breakout_threshold"])
            and prev["close"] >= prev["support"]
            and last["close"] < last["vwap"]
            and last["rsi"] < 50
        ):
            if verbose:
                name = symbol or ("CRYPTO" if is_crypto else "STOCK")
                logger.info(
                    f"✅ Breakout SHORT {name}: "
                    f"Price={last['close']:.2f}, Support={last['support']:.2f}"
                )
            return "short"

        return None


__all__ = ["ScalpingSignals", "MomentumSignals", "BreakoutSignals"]
