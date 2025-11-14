"""Trading configuration objects."""


class TradingConfig:
    """Day trading configuration - CRYPTO OPTIMIZED"""

    # Symbols
    STOCK_SYMBOLS = [
        "SPY",
        "QQQ",
        "AAPL",
        "MSFT",
        "META",
        "GOOGL",
        "NVDA",
        "AMZN",
        "TSLA",
    ]

    CRYPTO_PAIRS = ["BTC/USDT"]

    # Timeframes for day trading
    STOCK_TIMEFRAMES = ["5Min", "15Min", "1H"]
    CRYPTO_TIMEFRAMES = ["5m", "15m", "1h"]

    # Minimum USD volume required per symbol to treat the pair as tradable intraday
    CRYPTO_MIN_VOL = {
        "BTC/USDT": 150000,
        "ETH/USDT": 30000,
        "SOL/USDT": 15000,
    }

    # ATR multiples for position sizing and stop/profit calculations
    CRYPTO_ATR_MULT = {
        "BTC/USDT": 2.0,
        "ETH/USDT": 1.5,
        "SOL/USDT": 1.0,
    }

    # Trading hours (ET)
    MARKET_OPEN_HOUR = 10
    MARKET_OPEN_MINUTE = 0
    MARKET_CLOSE_HOUR = 15
    MARKET_CLOSE_MINUTE = 30
    FORCE_CLOSE_HOUR = 15
    FORCE_CLOSE_MINUTE = 30

    # Risk management
    BASE_RISK_PER_TRADE = 0.003  # 0.3% per trade
    MAX_POSITIONS = 3
    MAX_EQUITY_EXPOSURE = 0.30
    MAX_DAILY_LOSS = 0.015

    # Cooldown
    MIN_MINUTES_BETWEEN_TRADES = 10
    MAX_TRADES_PER_DAY = 12
    MAX_POSITIONS_PER_SYMBOL = 2
    MAX_CRYPTO_POSITION_PCT = 0.10

    # Strategy parameters tuned for crypto scalping
    SCALPING = {
        "active_hours": [(10, 0, 15, 30)],
        "min_volume_stock": 25000,
        "min_volume_usd_crypto": 150000,  # Minimum USD volume before taking a crypto scalp
        "require_volume_surge": False,
        # Risk/reward tuning expressed in ATR multiples
        "profit_target_atr_mult": 3.5,  # ATR-multiple distance to the take-profit
        "stop_loss_atr_mult": 2.5,  # ATR-multiple distance to the protective stop
        # RSI guardrails to focus on trending environments
        "rsi_min": 50,  # Ignore longs until RSI indicates bullish momentum
        "rsi_max": 75,  # Avoid entries at exhaustion extremes
        "require_trend_alignment": True,
        "enable_shorts": False,
    }

    MOMENTUM = {
        "active_hours": [(10, 0, 15, 30)],
        "min_volume_stock": 100000,
        "min_volume_usd_crypto": 200000,
        "require_volume_surge": False,
        "profit_target_atr_mult": 2.5,
        "stop_loss_atr_mult": 1.25,
        "rsi_min": 40,
        "rsi_max": 85,
        "require_trend_alignment": True,
    }

    BREAKOUT = {
        "active_hours": [(10, 0, 15, 0)],
        "min_volume_stock": 250000,
        "min_volume_usd_crypto": 200000,
        "require_volume_surge": False,
        "profit_target_atr_mult": 3.0,
        "stop_loss_atr_mult": 1.5,
        "consolidation_bars": 20,
        "breakout_threshold": 1.015,
    }

    # Costs
    STOCK_SLIPPAGE_BPS = 1.5
    STOCK_FEE_PCT = 0.0
    CRYPTO_SLIPPAGE_BPS = 3.0
    CRYPTO_FEE_PCT = 0.0015

    MIN_ORDER_NOTIONAL = 100
    LOOP_SLEEP_SECONDS = 60


class BacktestConfig:
    ENABLE = False
    START, END = "2025-10-20", "2025-11-01" # backtest works within 60 days from current date


__all__ = ["TradingConfig", "BacktestConfig"]
