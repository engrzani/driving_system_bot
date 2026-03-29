"""
config.py — Loads all configuration from .env and config.json.
"""
import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class Config:
    def __init__(self, config_file: str = "config.json"):
        self._load_json(config_file)
        self._load_env()
        self._validate()

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def _load_json(self, config_file: str):
        try:
            with open(config_file, "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            logger.error(f"config.json not found — using defaults.")
            data = {}

        self.test_centres: list = data.get("test_centres", [])
        self.date_range_days: int = data.get("date_range_days", 90)
        self.time_preference: str = data.get("time_preference", "any").lower()
        self.refresh_interval: int = data.get("refresh_interval_seconds", 30)
        self.repeat_alert_interval: int = data.get("repeat_alert_interval_seconds", 120)
        self.headless: bool = data.get("headless", False)
        self.sound_alert: bool = data.get("sound_alert", True)
        self.save_screenshots: bool = data.get("save_screenshots", True)
        self.cookies_file: str = data.get("cookies_file", "cookies.json")

    def _load_env(self):
        # DVSA credentials
        self.username: str = os.getenv("DVSA_USERNAME", "").replace(" ", "")
        self.password: str = os.getenv("DVSA_PASSWORD", "")

        # Telegram
        self.telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

        # WhatsApp via Twilio
        self.twilio_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
        self.twilio_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.twilio_from: str = os.getenv("TWILIO_WHATSAPP_FROM", "")
        self.whatsapp_to: str = os.getenv("WHATSAPP_TO_NUMBER", "")

    def _validate(self):
        if not self.username or not self.password:
            logger.warning("DVSA credentials missing — set DVSA_USERNAME and DVSA_PASSWORD in .env")

        if not self.test_centres:
            logger.warning("No test centres configured in config.json")

        telegram_ok = bool(self.telegram_bot_token and self.telegram_chat_id and
                           "YOUR_" not in self.telegram_bot_token and
                           "YOUR_" not in self.telegram_chat_id)
        whatsapp_ok = bool(self.twilio_sid and self.twilio_token and
                           "YOUR_" not in self.twilio_sid)

        self.telegram_enabled: bool = telegram_ok
        self.whatsapp_enabled: bool = whatsapp_ok

        if not telegram_ok and not whatsapp_ok:
            logger.warning("No notification channel configured. "
                           "Add Telegram or Twilio credentials to .env")
