# Day Trading Agent

Automated intraday system that scans US equities via Alpaca and liquid crypto pairs via BinanceUS, evaluates multiple indicator-driven strategies (scalping, momentum, breakout), and executes paper, live, or backtest sessions through a single CLI entrypoint.

## Features
- Multi-asset support: US stocks (Alpaca) and BTC/USDT crypto feed (BinanceUS through `ccxt`)
- Strategy stack with ATR- and RSI-aware scalping, momentum, and breakout playbooks configurable in `config.py`
- Centralized risk controls (position limits, max daily loss, cooldowns) and cost modeling
- Local persistence in `trader_day.sqlite` plus structured logging to `daytrader.log`
- Backtest harness that reuses the same indicators (`ta`, VWAP, ATR) and execution rules used in live trading

## Requirements
- Python 3.10+ (tested with 3.11)
- Dependencies from `trading_agents/requirements.txt`
  ```bash
  pip install -r trading_agents/requirements.txt
  ```
- Alpaca paper/live credentials for equities, and optional BinanceUS keys for live crypto orders

## Quick Start
1. **Create a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```
2. **Install dependencies**
   ```bash
   pip install -r trading_agents/requirements.txt
   ```
3. **Add a `.env` file** (see example below) at the repository root or wherever you launch `python trading_agents/day_trading_agent.py`.
4. **Run the CLI**
   ```bash
   python trading_agents/day_trading_agent.py
   ```
   - Mode `1` (default) -> paper trading against Alpaca's paper API plus BinanceUS public data
   - Mode `2` -> live trading (requires confirmation and live keys)
   - Mode `3` -> backtest; optionally override `BacktestConfig` dates when prompted

You can also launch via module: `python -m day_trading.cli` from within `trading_agents/`.

## Environment Configuration
`day_trading/settings.py` calls `load_dotenv()` at process start, so populate the required keys in a `.env` file before running the agent. Keep this file out of version control.

```env
# Alpaca paper trading (required for paper/backtest)
APCA_PAPER_API_KEY_ID=your-paper-key
APCA_PAPER_API_SECRET_KEY=your-paper-secret

# Alpaca live trading (only required when running Mode 2)
APCA_API_KEY_ID=your-live-key
APCA_API_SECRET_KEY=your-live-secret

# BinanceUS live crypto trading (only used in live mode)
BINANCE_API_KEY=your-binance-key
BINANCE_SECRET_KEY=your-binance-secret
```

If you omit live keys, the agent will gracefully fall back to paper-only execution.

## Strategy & Risk Settings
- Edit `trading_agents/day_trading/config.py` to control:
  - Tradable universes and timeframes (`STOCK_SYMBOLS`, `CRYPTO_PAIRS`, `*_TIMEFRAMES`)
  - Volume gates, ATR multipliers, RSI guardrails per strategy (`SCALPING`, `MOMENTUM`, `BREAKOUT`)
  - Risk management: per-trade risk budget, open-position limits, max daily loss, and cooldowns
  - Transaction cost assumptions used when sizing positions and evaluating exits
- Indicator calculations live in `indicators.py` (VWAP, ATR, RSI, momentum filters) and are shared by live and backtest runs so analytics stay consistent.

## Data, Storage, and Logs
- **Historical bars:** Pulled via `yfinance` for stocks and `ccxt` BinanceUS for crypto, then normalized and enriched with VWAP/ATR/RSI before signal generation.
- **State DB:** `trader_day.sqlite` stores open positions and historical trades so the agent can resume after restarts.
- **Logs:** `daytrader.log` plus stdout capture lifecycle events, fills, and backtest summaries. Adjust `logging.basicConfig` in `settings.py` if you prefer another sink.

## Backtesting Tips
- Toggle `BacktestConfig.ENABLE` or select Mode `3` in the CLI. You can accept default dates or provide a custom range.
- Backtests iterate across the default equity/crypto universe defined in `TradingConfig`. Modify the lists for bespoke studies.
- Results (fills, P&L per trade) are appended to `trader_day.sqlite`, making it easy to query performance with any SQLite client.

## Next Steps
- Wire the agent into your scheduler or dashboard scripts (`trading_day_dashboard.sh`) once comfortable with paper results.
- Consider monitoring `daytrader.log` with `tail -f` during live runs to catch connectivity or risk limit warnings early.
