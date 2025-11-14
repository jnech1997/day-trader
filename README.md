# Day Trading Agent

Python-based intraday trading system that scans a curated universe of US equities and BTC/USDT, evaluates indicator-driven strategies, and routes orders through Alpaca (equities) and BinanceUS (crypto). The project ships with a CLI runner, indicator/risk libraries, SQLite-backed state management, and optional dashboard scripts for monitoring fills.

> **Note:** Educational project only. Markets are risky and this code does not constitute financial advice.

## Repository Layout

| Path | Description |
| ---- | ----------- |
| `day_trading/` | Day trading package (agent orchestration, CLI, strategy config, indicators, risk controls, persistence). |
| `day_trading_agent.py` | Convenience wrapper so you can run `python day_trading_agent.py`. |
| `requirements.txt` | Shared Python dependencies. |
| `trading_day_dashboard.sh` | Terminal dashboard that reads `trader_day.sqlite` and surfaces P&L, win-rate, and open positions. |
| `trader_day.sqlite` / `daytrader.log` | SQLite state DB and rotating log file created at runtime. |

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # then edit with your keys
python day_trading_agent.py
```

Choose a mode in the CLI prompt:

- `1` -> paper trading (default)
- `2` -> live trading (requires confirmation and live keys)
- `3` -> backtest (optionally override the default date range)

Alternatively launch with `python -m day_trading.cli`.

## Environment Variables

Both the CLI and the agent load configuration from `.env`. Populate the placeholders in `.env.example` with your Alpaca and optional BinanceUS credentials. Keep the `.env` file out of version control.

```env
APCA_PAPER_API_KEY_ID=...
APCA_PAPER_API_SECRET_KEY=...
APCA_API_KEY_ID=...
APCA_API_SECRET_KEY=...
BINANCE_API_KEY=...
BINANCE_SECRET_KEY=...
```

## Development Notes

- **Indicators & Signals:** Located in `day_trading/indicators.py` and `day_trading/signals.py`. They compute VWAP, ATR, RSI, and strategy-specific triggers shared across live and backtest modes.
- **Risk Controls:** `day_trading/config.py` centralizes exposure limits, ATR-based stop/target multiples, symbol universes, and trading hours.
- **State Persistence:** Positions and trades live in `trader_day.sqlite` (see `day_trading/database.py`), allowing safe restarts and dashboard analytics.
- **Logging:** Configured via `day_trading/settings.py` to append to `daytrader.log` and stdout.

## Monitoring

Use the dashboard script while the agent is running:

```bash
./trading_day_dashboard.sh paper
```

It refreshes every five seconds, summarizing open positions, trade history, and performance metrics sourced from the SQLite DB.

## Backtesting

Select Mode `3` in the CLI to replay trades over historical data. You may accept the default window or enter a custom start/end date. Backtests reuse the live strategy stack, so results reflect real execution logic (including ATR-based position sizing and transaction cost modeling). Trade outcomes are recorded to the same SQLite database for later analysis.

## Next Steps

- Hook the agent into a scheduler or process manager if you want continuous operation.
- Extend `TradingConfig` with your own symbols or tweak ATR/RSI thresholds to experiment with different profiles.
