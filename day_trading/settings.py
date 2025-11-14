"""Common environment and logging setup for the day trading agent."""

from pathlib import Path
import logging

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("daytrader.log", mode="a"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("DayTrader")
DB_PATH = Path("./trader_day.sqlite").resolve()

__all__ = ["logger", "DB_PATH"]
