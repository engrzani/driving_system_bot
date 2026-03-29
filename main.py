"""
main.py — Entry point for the DVSA Pupil Test Slot Monitor (Option 2).

Run with:
    python main.py
"""
import asyncio
import logging
import sys

from colorama import Fore, Style, init

from config import Config
from monitor import SlotMonitor

init(autoreset=True)

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


BANNER = f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════╗
║    DVSA Pupil Test Slot Monitor  —  Option 2         ║
║    Enhanced Assistant Bot                            ║
╚══════════════════════════════════════════════════════╝{Style.RESET_ALL}

  {Fore.YELLOW}DISCLAIMER:{Style.RESET_ALL}
  This tool assists by alerting you the moment a slot appears.
  You complete the final booking step manually.
  Using automation on gov.uk services may be subject to their
  Terms of Use — use responsibly.

  Press  {Fore.GREEN}Ctrl+C{Style.RESET_ALL}  to stop the monitor at any time.
"""


async def main():
    print(BANNER)

    try:
        config = Config()
    except Exception as exc:
        logger.error(f"Failed to load config: {exc}")
        sys.exit(1)

    monitor = SlotMonitor(config)

    try:
        await monitor.start()
    except KeyboardInterrupt:
        logger.info("Stopped by user (Ctrl+C).")
        monitor.stop()
    except Exception as exc:
        logger.exception(f"Unexpected error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
