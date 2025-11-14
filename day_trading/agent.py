"""Day trading agent orchestration."""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import alpaca_trade_api as tradeapi
import ccxt
import numpy as np
import pandas as pd
import yfinance as yf

from .config import BacktestConfig, TradingConfig
from .database import StateDB
from .indicators import compute_intraday_indicators, compute_vwap, normalize_df
from .market import get_active_strategy, is_market_open, should_force_close
from .risk import apply_costs, calculate_stops_atr, update_trailing_stop
from .settings import DB_PATH, logger
from .signals import BreakoutSignals, MomentumSignals, ScalpingSignals


class DayTradingAgent:
    def __init__(self, paper_trading=True):
        self.paper_trading = paper_trading
        self.db = StateDB(DB_PATH)
        self.alpaca = self.crypto = None
        self.paper_positions: List[Dict] = []
        self.live_positions: Dict[int, Dict] = {}
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.trade_history = {}

        self._init_brokers()
        self._init_equity()

        if not self.paper_trading:
            self._load_live_positions()
        else:
            self._load_paper_positions()

    def _init_brokers(self):
        """Initialize broker connections"""
        try:
            self.alpaca = tradeapi.REST(
                key_id=os.getenv("APCA_PAPER_API_KEY_ID")
                if self.paper_trading
                else os.getenv("APCA_API_KEY_ID"),
                secret_key=os.getenv("APCA_PAPER_API_SECRET_KEY")
                if self.paper_trading
                else os.getenv("APCA_API_SECRET_KEY"),
                base_url="https://paper-api.alpaca.markets"
                if self.paper_trading
                else "https://api.alpaca.markets",
            )
            _ = self.alpaca.get_clock()
            logger.info("✓ Alpaca connected")
        except Exception as e:
            logger.warning(f"✗ Alpaca connect failed: {e}")
            self.alpaca = None

        if self.paper_trading:
            try:
                self.crypto = ccxt.binanceus({"enableRateLimit": True})
                self.crypto.load_markets()
                logger.info("✓ BinanceUS public (paper) ready")
            except Exception as e:
                logger.warning(f"✗ BinanceUS init failed: {e}")
                self.crypto = None
        else:
            try:
                self.crypto = ccxt.binanceus(
                    {
                        "apiKey": os.getenv("BINANCE_API_KEY"),
                        "secret": os.getenv("BINANCE_SECRET_KEY"),
                        "enableRateLimit": True,
                    }
                )
                self.crypto.load_markets()
                logger.info("✓ BinanceUS connected")
            except Exception as e:
                logger.warning(f"✗ BinanceUS connect failed: {e}")
                self.crypto = None

    def _fetch_alpaca_equity(self) -> float:
        """Fetch equity available in the Alpaca account."""
        if not self.alpaca:
            return 0.0
        try:
            return float(self.alpaca.get_account().equity)
        except Exception as exc:
            logger.warning(f"Unable to fetch Alpaca equity: {exc}")
            return 0.0

    def _fetch_crypto_equity(self) -> float:
        """Fetch total USD/USDT balance from BinanceUS for live trading."""
        if not self.crypto or self.paper_trading:
            return 0.0

        try:
            balance = self.crypto.fetch_balance()
        except Exception as exc:
            logger.warning(f"Unable to fetch Binance equity: {exc}")
            return 0.0

        total = 0.0
        for symbol in ("USD", "USDT"):
            wallet = balance.get(symbol) or {}
            if wallet:
                # Prefer 'total', fall back to free+used if needed
                total_amount = wallet.get("total")
                if total_amount is None:
                    free = wallet.get("free", 0.0) or 0.0
                    used = wallet.get("used", 0.0) or 0.0
                    total_amount = free + used
                try:
                    total += float(total_amount)
                except (TypeError, ValueError):
                    continue
        return total

    def _fetch_total_equity(self) -> Tuple[float, float, float]:
        """Get combined account equity and return both broker balances."""
        alpaca_eq = self._fetch_alpaca_equity()
        crypto_eq = self._fetch_crypto_equity()
        combined = alpaca_eq + crypto_eq
        if combined <= 0:
            combined = 100000.0  # fall back for paper trading or offline usage
        return combined, alpaca_eq, crypto_eq

    def _init_equity(self):
        total_eq, alpaca_eq, crypto_eq = self._fetch_total_equity()
        self.start_equity = total_eq
        if not self.paper_trading:
            logger.info(f"💵 Alpaca equity: ${alpaca_eq:,.2f}")
            logger.info(f"🪙 Binance equity: ${crypto_eq:,.2f}")
        logger.info(f"💰 Starting equity: ${self.start_equity:,.2f}")

    def _standardize_position(self, db_pos: dict) -> dict:
        return {
            "id": db_pos["id"],
            "symbol": db_pos["symbol"],
            "side": db_pos["side"],
            "entry": db_pos["entry_price"],
            "entry_price": db_pos["entry_price"],
            "qty": db_pos["qty_initial"],
            "qty_remaining": db_pos["qty_remaining"],
            "stop": db_pos["stop"],
            "target": db_pos["take"],
            "r": db_pos["r_value"],
            "broker": db_pos["broker"],
        }

    def _load_live_positions(self):
        positions = self.db.get_open_positions()
        for pos in positions:
            standardized = self._standardize_position(pos)
            self.live_positions[pos["id"]] = standardized
        if positions:
            logger.info(f"📥 Loaded {len(positions)} LIVE positions")

    def _load_paper_positions(self):
        positions = self.db.get_open_positions()
        for pos in positions:
            standardized = self._standardize_position(pos)
            self.paper_positions.append(standardized)
        if positions:
            logger.info(f"📥 Loaded {len(positions)} PAPER positions")

    def _get_bars_stock(self, sym: str, tf: str, period: str = "10d"):
        """Fetch stock intraday data"""
        tf_map = {"5Min": "5m", "15Min": "15m", "1H": "1h"}
        interval = tf_map.get(tf, "5m")

        try:
            if BacktestConfig.ENABLE:
                if tf == "5Min":
                    bars_per_day = 78
                    warmup_periods = 75
                elif tf == "15Min":
                    bars_per_day = 26
                    warmup_periods = 75
                elif tf == "1H":
                    bars_per_day = 6
                    warmup_periods = 75
                else:
                    bars_per_day = 26
                    warmup_periods = 75

                warmup_days = int(warmup_periods / bars_per_day) + 2

                start_date = pd.to_datetime(BacktestConfig.START) - timedelta(
                    days=warmup_days
                )
                end_date = pd.to_datetime(BacktestConfig.END) + timedelta(days=1)

                ticker = yf.Ticker(sym)
                df = ticker.history(
                    start=start_date.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                    interval=interval,
                    auto_adjust=True,
                )
            else:
                ticker = yf.Ticker(sym)
                df = ticker.history(period=period, interval=interval, auto_adjust=True)

            if df.empty:
                return None

            df = normalize_df(df)
            return df

        except Exception as e:
            logger.error(f"Failed to fetch {sym} {tf}: {e}")
            return None

    def _get_bars_crypto(self, pair: str, tf: str, limit: int = 500):
        """Fetch crypto intraday data"""
        if not self.crypto:
            return None

        tf = tf.replace("Min", "m").lower()

        try:
            if BacktestConfig.ENABLE:
                if tf == "5m":
                    bars_per_day = 288
                    warmup_periods = 75
                elif tf == "15m":
                    bars_per_day = 96
                    warmup_periods = 75
                elif tf == "1h":
                    bars_per_day = 24
                    warmup_periods = 75
                else:
                    bars_per_day = 96
                    warmup_periods = 75

                warmup_days = int(warmup_periods / bars_per_day) + 2

                start_date = pd.to_datetime(BacktestConfig.START) - timedelta(
                    days=warmup_days
                )
                end_date = pd.to_datetime(BacktestConfig.END) + timedelta(days=1)

                if start_date.tzinfo is None:
                    start_date = start_date.tz_localize("UTC")
                if end_date.tzinfo is None:
                    end_date = end_date.tz_localize("UTC")

                since = int(start_date.timestamp() * 1000)

                logger.info(
                    f"Fetching {pair} {tf} from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ({warmup_days}d warmup)"
                )

                all_data = []
                current_since = since
                max_iterations = 15

                for iteration in range(max_iterations):
                    chunk = self.crypto.fetch_ohlcv(
                        pair, timeframe=tf, since=current_since, limit=1000
                    )

                    if not chunk:
                        logger.info(
                            f"  Iteration {iteration + 1}: No more data available"
                        )
                        break

                    all_data.extend(chunk)
                    last_timestamp = chunk[-1][0]
                    last_datetime = pd.to_datetime(last_timestamp, unit="ms", utc=True)
                    logger.info(
                        f"  Iteration {iteration + 1}: Fetched {len(chunk)} bars, now at {last_datetime.strftime('%Y-%m-%d')}, total: {len(all_data)} bars"
                    )

                    if last_datetime >= end_date:
                        logger.info(
                            f"  ✓ Reached end date: {last_datetime.strftime('%Y-%m-%d')}"
                        )
                        break

                    if len(chunk) < 1000:
                        logger.info(
                            f"  ⚠️ Received only {len(chunk)} bars, end of available data"
                        )
                        break

                    current_since = last_timestamp + 1

                if not all_data:
                    logger.warning(f"No crypto data fetched for {pair} {tf}")
                    return None

                df = pd.DataFrame(
                    all_data,
                    columns=["timestamp", "open", "high", "low", "close", "volume"],
                )
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df = df.drop_duplicates(subset=["timestamp"])

                df = normalize_df(df)
                logger.info(
                    f"✓ Crypto fetch complete: {len(all_data)} bars → {len(df)} bars after dedup"
                )
                return df

            else:
                since = self.crypto.milliseconds() - (30 * 24 * 60 * 60 * 1000)
                ohlcv = self.crypto.fetch_ohlcv(
                    pair, timeframe=tf, since=since, limit=min(1000, limit)
                )

                if not ohlcv:
                    return None

                df = pd.DataFrame(
                    ohlcv,
                    columns=["timestamp", "open", "high", "low", "close", "volume"],
                )
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df = normalize_df(df)
                return df

        except Exception as e:
            logger.error(f"Failed to fetch {pair} {tf}: {e}")
            return None

    def _get_current_positions(self) -> List[dict]:
        return (
            self.paper_positions
            if self.paper_trading
            else list(self.live_positions.values())
        )

    def _can_open_position(self, symbol: str, notional: float) -> bool:
        """Check if we can open a new position"""
        positions = self._get_current_positions()

        if len(positions) >= TradingConfig.MAX_POSITIONS:
            logger.debug(f"Max positions reached ({TradingConfig.MAX_POSITIONS})")
            return False

        if self.trades_today >= TradingConfig.MAX_TRADES_PER_DAY:
            logger.debug(
                f"Max daily trades reached ({TradingConfig.MAX_TRADES_PER_DAY})"
            )
            return False

        last_trade_time = self.trade_history.get(symbol)
        if last_trade_time:
            time_since_last = datetime.now(timezone.utc) - last_trade_time
            if time_since_last < timedelta(
                minutes=TradingConfig.MIN_MINUTES_BETWEEN_TRADES
            ):
                logger.debug(
                    f"Cooldown active for {symbol} ({time_since_last.seconds // 60} min)"
                )
                return False

        current_exposure = sum(p["entry"] * p["qty_remaining"] for p in positions)
        max_exposure = self.start_equity * TradingConfig.MAX_EQUITY_EXPOSURE

        if (current_exposure + notional) > max_exposure:
            logger.debug(f"Max exposure would be exceeded")
            return False

        return True

    def open_position(
        self,
        symbol: str,
        side: str,
        price: float,
        atr: float,
        strategy: str,
        broker: str,
    ):
        """Open new position"""
        symbol_positions = [
            p for p in self._get_current_positions() if p["symbol"] == symbol
        ]
        if len(symbol_positions) >= TradingConfig.MAX_POSITIONS_PER_SYMBOL:
            return

        is_crypto = "/" in symbol

        risk_pct = TradingConfig.BASE_RISK_PER_TRADE
        risk_amount = self.start_equity * risk_pct

        stop, target = calculate_stops_atr(price, atr, side, strategy, symbol)

        stop_dist = abs(price - stop)
        stop_dist = max(stop_dist, price * 0.001)

        qty = risk_amount / stop_dist

        if qty * price < TradingConfig.MIN_ORDER_NOTIONAL:
            logger.debug(
                f"Position size too small: ${qty * price:.2f} < ${TradingConfig.MIN_ORDER_NOTIONAL}"
            )
            return

        if not self._can_open_position(symbol, qty * price):
            return

        target_dist = abs(target - price)
        risk_reward = target_dist / stop_dist

        if risk_reward < 1.2:
            logger.debug(f"Risk-reward too low: {risk_reward:.2f}")
            return

        entry_net, _ = apply_costs(price, price, side, is_crypto)

        if self.paper_trading:
            pos = {
                "symbol": symbol,
                "side": side,
                "entry": price,
                "entry_net": entry_net,
                "entry_price": price,
                "qty": qty,
                "qty_remaining": qty,
                "stop": stop,
                "target": target,
                "r": stop_dist,
                "broker": broker,
                "strategy": strategy,
                "atr": atr,
            }

            pos_id = self.db.save_position(pos)
            pos["id"] = pos_id
            self.paper_positions.append(pos)
            self.trades_today += 1
            self.trade_history[symbol] = datetime.now(timezone.utc)

            logger.info(
                f"  🟢 ENTRY [{symbol}] {side.upper()} | "
                f"Price: ${price:.2f} | Qty: {qty:.3f} | Stop: ${stop:.2f} | Target: ${target:.2f} | "
                f"RR: {risk_reward:.2f}:1 | Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"
            )

        else:
            shares = max(int(qty), 1) if not is_crypto else qty
            try:
                if broker == "alpaca":
                    self.alpaca.submit_order(
                        symbol=symbol,
                        qty=shares,
                        side=side,
                        type="market",
                        time_in_force="day",
                    )
                elif broker == "binanceus":
                    if side == "long":
                        self.crypto.create_market_buy_order(symbol, shares)
                    else:
                        self.crypto.create_market_sell_order(symbol, shares)

                pos = {
                    "symbol": symbol,
                    "side": side,
                    "entry": price,
                    "entry_net": entry_net,
                    "entry_price": price,
                    "qty": shares,
                    "qty_remaining": shares,
                    "stop": stop,
                    "target": target,
                    "r": stop_dist,
                    "broker": broker,
                    "strategy": strategy,
                    "atr": atr,
                }

                pos_id = self.db.save_position(pos)
                pos["id"] = pos_id
                self.live_positions[pos_id] = pos
                self.trades_today += 1
                self.trade_history[symbol] = datetime.now(timezone.utc)

                logger.info(
                    f"🟢 ENTRY [{strategy.upper()}] LIVE {side.upper()} {symbol} | "
                    f"Price: ${price:.2f} | Qty: {shares:.3f} | Stop: ${stop:.2f} | Target: ${target:.2f} | "
                    f"RR: {risk_reward:.2f}:1 | Broker: {broker}"
                )

            except Exception as e:
                logger.error(f"Failed to open {symbol} position: {e}")

    def _check_exits(self):
        """Check and execute exits for all positions"""
        if self.paper_trading:
            self._paper_check_exits()
        else:
            self._live_check_exits()

    def _paper_check_exits(self):
        """Check exits for paper positions with trailing stops"""
        if not self.paper_positions:
            return

        remaining = []
        for pos in self.paper_positions:
            symbol = pos["symbol"]
            side = pos["side"]
            is_crypto = "/" in symbol

            if is_crypto:
                df = self._get_bars_crypto(symbol, "5m", limit=100)
            else:
                df = self._get_bars_stock(symbol, "5Min", period="1d")

            if df is None or len(df) < 10:
                remaining.append(pos)
                continue

            df = compute_intraday_indicators(df)
            price = float(df["close"].iloc[-1])
            atr = float(df["atr"].iloc[-1])
            timestamp = df["timestamp"].iloc[-1]

            profit_pct = (
                ((price - pos["entry"]) / pos["entry"])
                if side == "long"
                else ((pos["entry"] - price) / pos["entry"])
            )
            if profit_pct > 0.01:
                stop_updated = update_trailing_stop(pos, price, atr, timestamp)
                if stop_updated and "id" in pos:
                    self.db.update_position(pos["id"], pos["stop"])

            target_hit = (
                (price >= pos["target"]) if side == "long" else (price <= pos["target"])
            )

            stop_hit = (
                (price <= pos["stop"]) if side == "long" else (price >= pos["stop"])
            )

            if target_hit or stop_hit:
                _, exit_net = apply_costs(pos["entry"], price, side, is_crypto)
                pnl = (
                    ((exit_net - pos["entry_net"]) * pos["qty_remaining"])
                    if side == "long"
                    else ((pos["entry_net"] - exit_net) * pos["qty_remaining"])
                )
                r_mult = (
                    ((price - pos["entry"]) / pos["r"])
                    if side == "long"
                    else ((pos["entry"] - price) / pos["r"])
                )

                reason = "TARGET" if target_hit else "STOP_LOSS"

                if "id" in pos:
                    self.db.close_position(pos["id"], price, pnl, r_mult, reason)

                self.daily_pnl += pnl

                logger.info(
                    f"  {'🟩' if pnl > 0 else '🟥'} EXIT [{symbol}] {reason} HIT | "
                    f"Entry: ${pos['entry']:.2f} | Exit: ${price:.2f} | "
                    f"P&L: ${pnl:.2f} | Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
                )
            else:
                remaining.append(pos)

        self.paper_positions = remaining

    def _live_check_exits(self):
        """Check exits for live positions with trailing stops"""
        if not self.live_positions:
            return

        positions_to_close = []

        for pos_id, pos in list(self.live_positions.items()):
            symbol = pos["symbol"]
            side = pos["side"]
            is_crypto = "/" in symbol

            if is_crypto:
                df = self._get_bars_crypto(symbol, "5m", limit=100)
            else:
                df = self._get_bars_stock(symbol, "5Min", period="1d")

            if df is None or len(df) < 10:
                continue

            df = compute_intraday_indicators(df)
            price = float(df["close"].iloc[-1])
            atr = float(df["atr"].iloc[-1])
            timestamp = df["timestamp"].iloc[-1]

            profit_pct = (
                ((price - pos["entry"]) / pos["entry"])
                if side == "long"
                else ((pos["entry"] - price) / pos["entry"])
            )
            if profit_pct > 0.01:
                stop_updated = update_trailing_stop(pos, price, atr, timestamp)
                if stop_updated:
                    self.db.update_position(pos_id, pos["stop"])

            target_hit = (
                (price >= pos["target"]) if side == "long" else (price <= pos["target"])
            )

            stop_hit = (
                (price <= pos["stop"]) if side == "long" else (price >= pos["stop"])
            )

            if target_hit or stop_hit:
                reason = "TARGET" if target_hit else "STOP_LOSS"
                positions_to_close.append((pos_id, pos, price, reason))

        for pos_id, pos, exit_price, reason in positions_to_close:
            self._execute_live_close(pos_id, pos, exit_price, reason)

    def _execute_live_close(
        self, pos_id: int, pos: dict, exit_price: float, reason: str
    ):
        """Execute live position close"""
        symbol = pos["symbol"]
        side = pos["side"]
        qty = pos["qty_remaining"]
        broker = pos["broker"]
        is_crypto = "/" in symbol

        _, exit_net = apply_costs(pos["entry"], exit_price, side, is_crypto)
        pnl = (
            ((exit_net - pos["entry_net"]) * qty)
            if side == "long"
            else ((pos["entry_net"] - exit_net) * qty)
        )
        r_mult = (
            ((exit_price - pos["entry"]) / pos["r"])
            if side == "long"
            else ((pos["entry"] - exit_price) / pos["r"])
        )

        try:
            if broker == "alpaca":
                close_side = "sell" if side == "long" else "buy"
                self.alpaca.submit_order(
                    symbol=symbol,
                    qty=int(qty),
                    side=close_side,
                    type="market",
                    time_in_force="day",
                )
            elif broker == "binanceus":
                if side == "long":
                    self.crypto.create_market_sell_order(symbol, qty)
                else:
                    self.crypto.create_market_buy_order(symbol, qty)

            logger.info(
                f"{'🟩' if pnl > 0 else '🟥'} EXIT {symbol} {side.upper()} | "
                f"Entry: ${pos['entry']:.2f} | Exit: ${exit_price:.2f} | "
                f"P&L: ${pnl:.2f} | R-Mult: {r_mult:.2f}R | Reason: {reason} | Broker: {broker}"
            )

            self.db.close_position(pos_id, exit_price, pnl, r_mult, reason)
            self.daily_pnl += pnl
            del self.live_positions[pos_id]

        except Exception as e:
            logger.error(f"Failed to close {symbol}: {e}")

    def close_all_positions(self):
        """Force close all positions (end of day)"""
        logger.info("⏰ Force closing all positions...")

        if self.paper_trading:
            for pos in self.paper_positions[:]:
                symbol = pos["symbol"]
                is_crypto = "/" in symbol

                if is_crypto:
                    df = self._get_bars_crypto(symbol, "5m", limit=100)
                else:
                    df = self._get_bars_stock(symbol, "5Min", period="1d")

                if df is None or len(df) < 10:
                    continue

                price = float(df["close"].iloc[-1])
                side = pos["side"]

                _, exit_net = apply_costs(pos["entry"], price, side, is_crypto)
                pnl = (
                    ((exit_net - pos["entry_net"]) * pos["qty_remaining"])
                    if side == "long"
                    else ((pos["entry_net"] - exit_net) * pos["qty_remaining"])
                )
                r_mult = (
                    ((price - pos["entry"]) / pos["r"])
                    if side == "long"
                    else ((pos["entry"] - price) / pos["r"])
                )

                if "id" in pos:
                    self.db.close_position(pos["id"], price, pnl, r_mult, "FORCE_CLOSE")

                self.daily_pnl += pnl
                logger.info(
                    f"⏰ FORCE CLOSE {symbol} {side.upper()} | "
                    f"Entry: ${pos['entry']:.2f} | Exit: ${price:.2f} | P&L: ${pnl:.2f}"
                )

            self.paper_positions = []

        else:
            for pos_id, pos in list(self.live_positions.items()):
                symbol = pos["symbol"]
                is_crypto = "/" in symbol

                if is_crypto:
                    df = self._get_bars_crypto(symbol, "5m", limit=100)
                else:
                    df = self._get_bars_stock(symbol, "5Min", period="1d")

                if df is None or len(df) < 10:
                    continue

                price = float(df["close"].iloc[-1])
                self._execute_live_close(pos_id, pos, price, "FORCE_CLOSE")

    def run_backtest(self):
        """Run backtest on historical data"""
        logger.info("=" * 80)
        logger.info("🧪 DAY TRADING BACKTEST")
        logger.info("=" * 80)
        logger.info(f"📅 Date range: {BacktestConfig.START} → {BacktestConfig.END}")
        logger.info("=" * 80)

        backtest_start = pd.to_datetime(BacktestConfig.START).tz_localize("UTC")
        backtest_end = pd.to_datetime(BacktestConfig.END).tz_localize(
            "UTC"
        ) + pd.Timedelta(days=1)

        universe = [
            ("SPY", "alpaca", False),
            ("QQQ", "alpaca", False),
            ("AAPL", "alpaca", False),
            ("MSFT", "alpaca", False),
            ("META", "alpaca", False),
            ("GOOGL", "alpaca", False),
            ("NVDA", "alpaca", False),
            ("AMZN", "alpaca", False),
            ("TSLA", "alpaca", False),
            ("BTC/USDT", "binanceus", True),
        ]

        all_trades = []
        total_pnl = 0.0
        last_trade_time = {}

        for symbol, broker, is_crypto in universe:
            logger.info(f"\n⏳ Backtesting {symbol}...")

            if is_crypto:
                logger.info(f"Fetching crypto data for {symbol}...")
                df_5m = self._get_bars_crypto(symbol, "5m", limit=1000)
                df_15m = self._get_bars_crypto(symbol, "15m", limit=1000)
                df_1h = self._get_bars_crypto(symbol, "1h", limit=1000)
            else:
                logger.info(f"Fetching stock data for {symbol}...")
                df_5m = self._get_bars_stock(symbol, "5Min", period="60d")
                df_15m = self._get_bars_stock(symbol, "15Min", period="60d")
                df_1h = self._get_bars_stock(symbol, "1H", period="60d")

            if any(df is None or df.empty for df in [df_5m, df_15m, df_1h]):
                logger.warning(f"{symbol}: No data available - skipping")
                continue

            data_start = df_15m["timestamp"].min()
            data_end = df_15m["timestamp"].max()
            logger.info(
                f"Available data: {data_start.strftime('%Y-%m-%d')} to {data_end.strftime('%Y-%m-%d')}"
            )
            logger.info(
                f"Backtest window: {backtest_start.strftime('%Y-%m-%d')} to {backtest_end.strftime('%Y-%m-%d')}"
            )

            df_5m = compute_vwap(df_5m)
            df_5m = compute_intraday_indicators(df_5m)
            df_15m = compute_vwap(df_15m)
            df_15m = compute_intraday_indicators(df_15m)
            df_1h = compute_vwap(df_1h)
            df_1h = compute_intraday_indicators(df_1h)

            if any(len(df) < 10 for df in [df_5m, df_15m, df_1h]):
                logger.info(f"{symbol}: Insufficient data after indicators")
                continue

            logger.info(
                f"Data: 5m={len(df_5m)} bars, 15m={len(df_15m)} bars, 1h={len(df_1h)} bars"
            )

            bars_in_window = len(
                df_15m[
                    (df_15m["timestamp"] >= backtest_start)
                    & (df_15m["timestamp"] < backtest_end)
                ]
            )
            logger.info(f"Bars in backtest window: {bars_in_window}")

            if bars_in_window == 0:
                logger.warning(f"{symbol}: No data in requested date range!")
                continue

            positions = []
            symbol_pnl = 0.0

            for idx in range(50, len(df_5m)):
                current_bar = df_5m.iloc[idx]
                current_time = current_bar["timestamp"]

                if current_time < backtest_start or current_time >= backtest_end:
                    continue

                if not is_crypto:
                    hour = current_time.hour
                    minute = current_time.minute
                    if hour < 10 or hour >= 15 or (hour == 15 and minute >= 30):
                        continue

                last_time = last_trade_time.get(symbol)
                if last_time:
                    time_diff = (current_time - last_time).total_seconds() / 60
                    if time_diff < TradingConfig.MIN_MINUTES_BETWEEN_TRADES:
                        continue

                for pos in positions:
                    if pos["status"] == "closed":
                        continue

                    if pos.get("entry_time") and pos["entry_time"] < backtest_start:
                        continue

                    current_price = current_bar["close"]
                    current_atr = current_bar["atr"]

                    profit_pct = (
                        ((current_price - pos["entry"]) / pos["entry"])
                        if pos["side"] == "long"
                        else ((pos["entry"] - current_price) / pos["entry"])
                    )
                    if profit_pct > 0.01:
                        update_trailing_stop(
                            pos, current_price, current_atr, current_time
                        )

                    if pos["side"] == "long":
                        if current_price >= pos["target"]:
                            exit_price = pos["target"]
                            _, exit_net = apply_costs(
                                pos["entry"], exit_price, pos["side"], is_crypto
                            )
                            pnl = (exit_net - pos["entry_net"]) * pos["qty"]
                            pos["status"] = "closed"
                            pos["exit_price"] = exit_price
                            pos["pnl"] = pnl
                            pos["exit_time"] = current_time
                            pos["reason"] = "TARGET"
                            symbol_pnl += pnl
                            all_trades.append(pos.copy())
                            logger.info(
                                f"  🟩 EXIT [{symbol}] TARGET HIT | "
                                f"Entry: ${pos['entry']:.2f} | Exit: ${exit_price:.2f} | "
                                f"P&L: ${pnl:.2f} | Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                        elif current_price <= pos["stop"]:
                            exit_price = pos["stop"]
                            _, exit_net = apply_costs(
                                pos["entry"], exit_price, pos["side"], is_crypto
                            )
                            pnl = (exit_net - pos["entry_net"]) * pos["qty"]
                            pos["status"] = "closed"
                            pos["exit_price"] = exit_price
                            pos["pnl"] = pnl
                            pos["exit_time"] = current_time
                            pos["reason"] = "STOP"
                            symbol_pnl += pnl
                            all_trades.append(pos.copy())
                            logger.info(
                                f"  🟥 EXIT [{symbol}] STOP HIT | "
                                f"Entry: ${pos['entry']:.2f} | Exit: ${exit_price:.2f} | "
                                f"P&L: ${pnl:.2f} | Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                    else:
                        if current_price <= pos["target"]:
                            exit_price = pos["target"]
                            _, exit_net = apply_costs(
                                pos["entry"], exit_price, pos["side"], is_crypto
                            )
                            pnl = (pos["entry_net"] - exit_net) * pos["qty"]
                            pos["status"] = "closed"
                            pos["exit_price"] = exit_price
                            pos["pnl"] = pnl
                            pos["exit_time"] = current_time
                            pos["reason"] = "TARGET"
                            symbol_pnl += pnl
                            all_trades.append(pos.copy())
                            logger.info(
                                f"  🟩 EXIT [{symbol}] TARGET HIT | "
                                f"Entry: ${pos['entry']:.2f} | Exit: ${exit_price:.2f} | "
                                f"P&L: ${pnl:.2f} | Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                        elif current_price >= pos["stop"]:
                            exit_price = pos["stop"]
                            _, exit_net = apply_costs(
                                pos["entry"], exit_price, pos["side"], is_crypto
                            )
                            pnl = (pos["entry_net"] - exit_net) * pos["qty"]
                            pos["status"] = "closed"
                            pos["exit_price"] = exit_price
                            pos["pnl"] = pnl
                            pos["exit_time"] = current_time
                            pos["reason"] = "STOP"
                            symbol_pnl += pnl
                            all_trades.append(pos.copy())
                            logger.info(
                                f"  🟥 EXIT [{symbol}] STOP HIT | "
                                f"Entry: ${pos['entry']:.2f} | Exit: ${exit_price:.2f} | "
                                f"P&L: ${pnl:.2f} | Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}"
                            )

                positions = [p for p in positions if p["status"] != "closed"]

                symbol_positions = [
                    p
                    for p in positions
                    if p["status"] == "open" and p["symbol"] == symbol
                ]
                if len(symbol_positions) >= TradingConfig.MAX_POSITIONS_PER_SYMBOL:
                    continue

                lookback_df = df_5m.iloc[: idx + 1]

                signal = ScalpingSignals.check_signal(
                    lookback_df,
                    TradingConfig.SCALPING,
                    is_crypto=is_crypto,
                    verbose=True,
                    symbol=symbol,
                )

                if signal:
                    entry_price = current_bar["close"]
                    atr = current_bar["atr"]

                    risk_pct = TradingConfig.BASE_RISK_PER_TRADE
                    risk_amount = self.start_equity * risk_pct

                    stop, target = calculate_stops_atr(
                        entry_price, atr, signal, "scalping", symbol
                    )
                    stop_dist = abs(entry_price - stop)
                    target_dist = abs(target - entry_price)
                    risk_reward = target_dist / stop_dist

                    if risk_reward < 1.2:
                        continue

                    qty = risk_amount / max(stop_dist, 1e-9)

                    if qty * entry_price < TradingConfig.MIN_ORDER_NOTIONAL:
                        continue

                    entry_net, _ = apply_costs(
                        entry_price, entry_price, signal, is_crypto
                    )

                    pos = {
                        "symbol": symbol,
                        "side": signal,
                        "entry": entry_price,
                        "entry_net": entry_net,
                        "qty": qty,
                        "stop": stop,
                        "target": target,
                        "entry_time": current_time,
                        "status": "open",
                        "strategy": "scalping",
                    }
                    positions.append(pos)
                    last_trade_time[symbol] = current_time

                    logger.info(
                        f"  🟢 ENTRY [{symbol}] {signal.upper()} | "
                        f"Price: ${entry_price:.2f} | Qty: {qty:.3f} | "
                        f"Stop: ${stop:.2f} | Target: ${target:.2f} | RR: {risk_reward:.2f}:1 | "
                        f"Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}"
                    )

            for pos in positions:
                if pos["status"] == "open":
                    exit_price = df_5m.iloc[-1]["close"]
                    exit_time = df_5m.iloc[-1]["timestamp"]
                    _, exit_net = apply_costs(
                        pos["entry"], exit_price, pos["side"], is_crypto
                    )
                    if pos["side"] == "long":
                        pnl = (exit_net - pos["entry_net"]) * pos["qty"]
                    else:
                        pnl = (pos["entry_net"] - exit_net) * pos["qty"]
                    pos["status"] = "closed"
                    pos["exit_price"] = exit_price
                    pos["pnl"] = pnl
                    pos["exit_time"] = exit_time
                    pos["reason"] = "EOD"
                    symbol_pnl += pnl
                    all_trades.append(pos.copy())

            symbol_trades = [t for t in all_trades if t["symbol"] == symbol]
            symbol_wins = [t for t in symbol_trades if t["pnl"] > 0]
            logger.info(
                f"{symbol}: {len(symbol_trades)} trades | "
                f"Wins: {len(symbol_wins)} | P&L: ${symbol_pnl:.2f}"
            )
            total_pnl += symbol_pnl

        logger.info("\n" + "=" * 80)
        logger.info("📊 BACKTEST RESULTS")
        logger.info("=" * 80)
        logger.info(f"Total Trades: {len(all_trades)}")
        logger.info(f"Total P&L: ${total_pnl:.2f}")
        logger.info(f"Return: {(total_pnl / self.start_equity) * 100:.2f}%")

        if all_trades:
            wins = [t for t in all_trades if t["pnl"] > 0]
            losses = [t for t in all_trades if t["pnl"] <= 0]
            win_rate = len(wins) / len(all_trades) * 100
            avg_win = np.mean([t["pnl"] for t in wins]) if wins else 0
            avg_loss = np.mean([t["pnl"] for t in losses]) if losses else 0

            total_wins = sum([t["pnl"] for t in wins]) if wins else 0
            total_losses = abs(sum([t["pnl"] for t in losses])) if losses else 1

            logger.info(f"Win Rate: {win_rate:.1f}%")
            logger.info(f"Avg Win: ${avg_win:.2f}")
            logger.info(f"Avg Loss: ${avg_loss:.2f}")
            logger.info(f"Profit Factor: {total_wins / total_losses:.2f}")

            if avg_loss != 0:
                logger.info(f"Win/Loss Ratio: {abs(avg_win / avg_loss):.2f}")

        logger.info("=" * 80)

    def run(self):
        """Run live/paper day trading"""
        logger.info("=" * 80)
        logger.info("🚀 DAY TRADING AGENT")
        logger.info("=" * 80)
        logger.info(f"Mode: {'PAPER' if self.paper_trading else '⚠️ LIVE'}")
        logger.info(
            f"Symbols: stocks={TradingConfig.STOCK_SYMBOLS}, crypto={TradingConfig.CRYPTO_PAIRS}"
        )
        logger.info(f"Risk: {TradingConfig.BASE_RISK_PER_TRADE * 100:.2f}% per trade")
        logger.info(f"Max Positions: {TradingConfig.MAX_POSITIONS}")
        logger.info(f"Max Daily Trades: {TradingConfig.MAX_TRADES_PER_DAY}")
        logger.info(f"Cooldown: {TradingConfig.MIN_MINUTES_BETWEEN_TRADES} min")
        logger.info("=" * 80)

        scan_count = 0

        try:
            while True:
                scan_count += 1
                logger.info(f"\n{'=' * 80}")
                logger.info(
                    f"🔄 Scan #{scan_count} - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                )
                logger.info(f"{'=' * 80}")

                if not is_market_open():
                    logger.info("🔴 Market closed")
                    time.sleep(300)
                    continue

                if should_force_close():
                    self.close_all_positions()
                    logger.info("✅ All positions closed. Stopping for the day.")
                    break

                if self.daily_pnl < -self.start_equity * TradingConfig.MAX_DAILY_LOSS:
                    logger.warning("🚨 Daily loss limit reached")
                    self.close_all_positions()
                    break

                strategy = get_active_strategy()
                if not strategy:
                    logger.info("⏸️  Outside active trading hours")
                    time.sleep(60)
                    continue

                logger.info(f"📊 Strategy: {strategy.upper()}")

                self._check_exits()

                # Scan crypto
                for pair in TradingConfig.CRYPTO_PAIRS:
                    try:
                        if any(
                            p["symbol"] == pair for p in self._get_current_positions()
                        ):
                            continue

                        if strategy == "scalping":
                            df = self._get_bars_crypto(pair, "5m", limit=200)
                            if df is None or len(df) < 50:
                                continue
                            df = compute_vwap(df)
                            df = compute_intraday_indicators(df)

                            signal = ScalpingSignals.check_signal(
                                df,
                                TradingConfig.SCALPING,
                                is_crypto=True,
                                verbose=True,
                                symbol=pair,
                            )

                        elif strategy == "momentum":
                            df = self._get_bars_crypto(pair, "15m", limit=200)
                            df_1h = self._get_bars_crypto(pair, "1h", limit=200)

                            if df is None or len(df) < 50 or df_1h is None:
                                continue

                            df = compute_vwap(df)
                            df = compute_intraday_indicators(df)
                            df_1h = compute_vwap(df_1h)
                            df_1h = compute_intraday_indicators(df_1h)

                            signal = MomentumSignals.check_signal(
                                df,
                                df_1h,
                                TradingConfig.MOMENTUM,
                                is_crypto=True,
                                verbose=True,
                                symbol=pair,
                            )

                        else:
                            df = self._get_bars_crypto(pair, "1h", limit=200)
                            if df is None or len(df) < 50:
                                continue
                            df = compute_vwap(df)
                            df = compute_intraday_indicators(df)

                            signal = BreakoutSignals.check_signal(
                                df,
                                TradingConfig.BREAKOUT,
                                is_crypto=True,
                                verbose=True,
                                symbol=pair,
                            )

                        if signal:
                            price = float(df["close"].iloc[-1])
                            atr = float(df["atr"].iloc[-1])
                            broker = (
                                "paper-crypto" if self.paper_trading else "binanceus"
                            )
                            self.open_position(
                                pair, signal, price, atr, strategy, broker
                            )

                        time.sleep(0.2)

                    except Exception as e:
                        logger.error(f"Error scanning {pair}: {e}")
                        continue

                positions = self._get_current_positions()
                logger.info(f"\n✅ Scan complete")
                logger.info(
                    f"📊 Positions: {len(positions)}/{TradingConfig.MAX_POSITIONS} | "
                    f"Trades: {self.trades_today}/{TradingConfig.MAX_TRADES_PER_DAY} | "
                    f"Daily P&L: ${self.daily_pnl:.2f}"
                )

                logger.info(f"💤 Next scan in {TradingConfig.LOOP_SLEEP_SECONDS}s...")
                time.sleep(TradingConfig.LOOP_SLEEP_SECONDS)

        except KeyboardInterrupt:
            logger.info("⏹️ Stopped by user")
            self.close_all_positions()
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            raise


# ============================================================
# MAIN
# ============================================================
