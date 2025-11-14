"""CLI entrypoint for the day trading agent."""

from __future__ import annotations

import textwrap

from .agent import DayTradingAgent
from .config import BacktestConfig
from .settings import logger


def _print_banner() -> None:
    """Display a concise overview so new users know what to expect."""
    summary = textwrap.dedent(
        """
        ==============================================================================
        DAY TRADING AGENT
        - Routes equities through Alpaca and crypto through BinanceUS (via ccxt)
        - Uses indicator-driven scalping, momentum, and breakout playbooks
        - Shares the same analytics stack across live, paper, and backtest modes
        ==============================================================================
        """
    ).strip("\n")
    print("\n" + summary + "\n")


def _prompt_mode() -> str:
    """Prompt the user for a run mode."""
    menu = textwrap.dedent(
        """
        Select a run mode:
          [1] Paper trading (default) - exercises the full flow without real capital
          [2] Live trading           - submits orders using live Alpaca/Binance keys
          [3] Backtest               - replays strategies on historical data
        """
    ).rstrip()
    print(menu)
    mode = input("Mode (1/2/3): ").strip()
    if mode not in {"1", "2", "3"}:
        logger.warning("Invalid mode selection, defaulting to paper trading.")
        return "1"
    return mode


def _configure_backtest() -> None:
    """Allow the user to override the default date range."""
    logger.info("Backtest mode selected")
    BacktestConfig.ENABLE = True
    custom = input("Use a custom date range? (y/N): ").strip().lower()
    if custom == "y":
        start = input(
            f"Start date (YYYY-MM-DD, default={BacktestConfig.START}): "
        ).strip()
        end = input(f"End date (YYYY-MM-DD, default={BacktestConfig.END}): ").strip()
        if start:
            BacktestConfig.START = start
        if end:
            BacktestConfig.END = end
    logger.info(
        "Backtest window configured: %s -> %s",
        BacktestConfig.START,
        BacktestConfig.END,
    )


def main():
    _print_banner()
    mode = _prompt_mode()

    if mode == "3":
        _configure_backtest()
        DayTradingAgent(True).run_backtest()
        return

    paper = mode != "2"
    if not paper:
        print("\n⚠️  WARNING: LIVE TRADING MODE ⚠️")
        print("This will trade with REAL MONEY!")
        confirm = input("Type 'CONFIRM' to proceed: ")
        if confirm != "CONFIRM":
            print("Exiting...")
            return

    DayTradingAgent(paper).run()


if __name__ == "__main__":
    main()
