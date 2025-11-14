"""Risk management helpers (stops, trailing logic, and costs)."""

from __future__ import annotations

from typing import Tuple

from .config import TradingConfig
from .settings import logger


def calculate_stops_atr(
    price: float, atr: float, side: str, strategy: str, symbol: str
) -> Tuple[float, float]:
    """Calculate ATR-based stops and targets - CRYPTO OPTIMIZED"""
    is_crypto = "/" in symbol

    if is_crypto:
        stop_mult = 2.5
        target_mult = 3.5
    else:
        if strategy == "momentum":
            config = TradingConfig.MOMENTUM
        elif strategy == "breakout":
            config = TradingConfig.BREAKOUT
        else:
            config = TradingConfig.SCALPING

        stop_mult = config["stop_loss_atr_mult"]
        target_mult = config["profit_target_atr_mult"]

    if side == "long":
        stop = price - atr * stop_mult
        target = price + atr * target_mult
    else:
        stop = price + atr * stop_mult
        target = price - atr * target_mult

    return stop, target


def update_trailing_stop(
    pos: dict, current_price: float, atr: float, timestamp=None
) -> bool:
    """
    🔒 CRYPTO-OPTIMIZED Trailing Stop:
    - Only trails after 1.5% profit
    - Wider multiplier (1.8x ATR)
    - Requires bigger moves to update
    """
    symbol = pos.get("symbol", "")
    side = pos.get("side", "long")
    old_stop = pos["stop"]

    if timestamp:
        last_update = pos.get("last_trail_update")
        if last_update == timestamp:
            return False
        pos["last_trail_update"] = timestamp

    is_crypto = "/" in symbol

    if is_crypto:
        profit_pct = (
            ((current_price - pos["entry"]) / pos["entry"])
            if side == "long"
            else ((pos["entry"] - current_price) / pos["entry"])
        )

        if profit_pct < 0.015:
            return False

        trail_mult = 1.8
        min_move = atr * 1.0

        if side == "long":
            desired_stop = current_price - trail_mult * atr

            if desired_stop > old_stop + min_move:
                pos["stop"] = desired_stop
                logger.info(
                    f"🔒 Trailing stop updated [{symbol}]: "
                    f"${old_stop:.2f} → ${desired_stop:.2f} (profit: {profit_pct * 100:.1f}%)"
                )
                return True

        else:
            desired_stop = current_price + trail_mult * atr

            if desired_stop < old_stop - min_move:
                pos["stop"] = desired_stop
                logger.info(
                    f"🔒 Trailing stop updated [{symbol}]: "
                    f"${old_stop:.2f} → ${desired_stop:.2f} (profit: {profit_pct * 100:.1f}%)"
                )
                return True

        return False

    trail_mult = 1.5

    if side == "long":
        new_stop = current_price - (trail_mult * atr)
        if new_stop > pos["stop"]:
            old_stop = pos["stop"]
            pos["stop"] = new_stop
            logger.info(
                f"🔒 Trailing stop updated [{symbol}]: ${old_stop:.2f} → ${new_stop:.2f}"
            )
            return True

    else:
        new_stop = current_price + (trail_mult * atr)
        if new_stop < pos["stop"]:
            old_stop = pos["stop"]
            pos["stop"] = new_stop
            logger.info(
                f"🔒 Trailing stop updated [{symbol}]: ${old_stop:.2f} → ${new_stop:.2f}"
            )
            return True

    return False


def apply_costs(entry: float, exit_: float, side: str, is_crypto: bool):
    """Apply slippage and fees"""
    if is_crypto:
        slippage = TradingConfig.CRYPTO_SLIPPAGE_BPS / 10000.0
        fee = TradingConfig.CRYPTO_FEE_PCT
    else:
        slippage = TradingConfig.STOCK_SLIPPAGE_BPS / 10000.0
        fee = TradingConfig.STOCK_FEE_PCT

    if side == "long":
        entry_net = entry * (1 + slippage + fee)
        exit_net = exit_ * (1 - slippage - fee)
    else:
        entry_net = entry * (1 - slippage - fee)
        exit_net = exit_ * (1 + slippage - fee)

    return entry_net, exit_net


__all__ = ["calculate_stops_atr", "update_trailing_stop", "apply_costs"]
