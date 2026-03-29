"""
notifier.py — Delivers alerts via Telegram, WhatsApp (Twilio), and Windows sound.

Telegram is the primary channel (free, instant).
WhatsApp via Twilio is optional (requires a paid Twilio account).
Windows sound plays locally whenever a slot is found.
"""
import asyncio
import logging
import sys
from typing import Optional

try:
    import winsound
    _WINSOUND_AVAILABLE = sys.platform == "win32"
except ImportError:
    _WINSOUND_AVAILABLE = False

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, config):
        self.config = config
        self._tg_bot = None

        if config.telegram_enabled:
            try:
                from telegram import Bot
                self._tg_bot = Bot(token=config.telegram_bot_token)
                logger.info("Telegram notifications enabled.")
            except Exception as exc:
                logger.warning(f"Telegram init failed: {exc}")
                self._tg_bot = None

        if config.whatsapp_enabled:
            logger.info("WhatsApp (Twilio) notifications enabled.")

    # ── Public methods ────────────────────────────────────────────────────────

    async def send_slot_alert(self, slot: dict):
        """Send a full slot-found alert via all configured channels."""
        date_str = str(slot.get("date", "unknown"))
        time_str = str(slot.get("time", ""))
        centre   = slot.get("centre", "unknown")
        url      = slot.get("page_url", "")

        msg = (
            f"🚨 SLOT AVAILABLE!\n\n"
            f"📍 Centre : {centre}\n"
            f"📅 Date   : {date_str}\n"
            f"⏰ Time   : {time_str}\n"
        )
        if url:
            msg += f"\n🔗 {url}\n"
        msg += "\n➡️  Act now — the page has been opened for you!"

        self._sound_alert()
        await self.send_text(msg)

    async def send_text(self, message: str):
        """Send a plain-text message through all configured channels."""
        await self._send_telegram(message)
        await self._send_whatsapp(message)

    async def send_photo(self, image_bytes: bytes, caption: str = ""):
        """Send a photo (screenshot) via Telegram."""
        if not self._tg_bot or not self.config.telegram_chat_id:
            return
        try:
            from telegram.error import TelegramError
            await self._tg_bot.send_photo(
                chat_id=self.config.telegram_chat_id,
                photo=image_bytes,
                caption=caption,
            )
        except Exception as exc:
            logger.warning(f"Telegram photo send failed: {exc}")

    # ── Channel implementations ───────────────────────────────────────────────

    async def _send_telegram(self, message: str):
        if not self._tg_bot or not self.config.telegram_chat_id:
            return
        for attempt in range(1, 4):
            try:
                from telegram.error import TelegramError
                await self._tg_bot.send_message(
                    chat_id=self.config.telegram_chat_id,
                    text=message,
                    read_timeout=30,
                    write_timeout=30,
                    connect_timeout=30,
                )
                logger.info("Telegram message sent.")
                return
            except Exception as exc:
                logger.warning(f"Telegram send attempt {attempt} failed: {exc}")
                if attempt < 3:
                    await asyncio.sleep(5)
        logger.error("Telegram send failed after 3 attempts.")

    async def _send_whatsapp(self, message: str):
        if not self.config.whatsapp_enabled:
            return
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._twilio_send, message)
            logger.info("WhatsApp message sent.")
        except Exception as exc:
            logger.error(f"WhatsApp send failed: {exc}")

    def _twilio_send(self, message: str):
        """Synchronous Twilio call — run in executor to avoid blocking."""
        from twilio.rest import Client
        client = Client(self.config.twilio_sid, self.config.twilio_token)
        client.messages.create(
            from_=f"whatsapp:{self.config.twilio_from}",
            to=f"whatsapp:{self.config.whatsapp_to}",
            body=message,
        )

    def _sound_alert(self):
        """Play three short beeps on Windows."""
        if not self.config.sound_alert or not _WINSOUND_AVAILABLE:
            return
        try:
            for _ in range(3):
                winsound.Beep(1200, 400)   # 1200 Hz for 400 ms
                winsound.Beep(800,  200)
        except Exception as exc:
            logger.debug(f"Sound alert unavailable: {exc}")
