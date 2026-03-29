"""
monitor.py — Core monitoring loop.

Iterates over configured test centres at a fixed interval, detects newly
available slots, fires alerts, and optionally clicks 'View' to pre-open
the reservation page.
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Set

from browser import DVSABrowser
from notifier import Notifier

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = "screenshots"


class SlotMonitor:
    """Runs the end-to-end monitoring loop."""

    def __init__(self, config):
        self.config = config
        self.browser = DVSABrowser(config)
        self.notifier = Notifier(config)

        # Track known slots so we only alert on *new* appearances
        self._known_slots: Set[str] = set()
        # Track when we last re-alerted about a slot (for repeat alerts)
        self._last_alerted: Dict[str, datetime] = {}
        self._running = False
        self._check_count = 0

        if config.save_screenshots:
            os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self):
        """Start the browser and enter the main monitoring loop."""
        self._running = True

        await self.browser.start()

        logger.info("Logging in to DVSA portal…")
        success = await self.browser.login()
        if not success:
            logger.error("Login failed — cannot start monitoring. "
                         "Check .env credentials and re-run.")
            await self.browser.close()
            return

        await self.browser.navigate_to_calendar()

        centres_list = ", ".join(self.config.test_centres)
        startup_msg = (
            f"DVSA Monitor STARTED\n"
            f"Centres: {centres_list}\n"
            f"Date range: next {self.config.date_range_days} days\n"
            f"Time preference: {self.config.time_preference}\n"
            f"Refresh every: {self.config.refresh_interval}s"
        )
        logger.info(startup_msg)
        await self.notifier.send_text(f"✅ {startup_msg}")

        try:
            while self._running:
                await self._run_check_cycle()
                logger.info(
                    f"[Check #{self._check_count}] Sleeping "
                    f"{self.config.refresh_interval}s…"
                )
                await asyncio.sleep(self.config.refresh_interval)
        finally:
            await self.browser.close()
            logger.info("Monitor stopped.")

    def stop(self):
        self._running = False

    # ── Check cycle ───────────────────────────────────────────────────────────

    async def _run_check_cycle(self):
        self._check_count += 1
        ts = datetime.now().strftime("%H:%M:%S")
        logger.info(f"[{ts}] Check #{self._check_count} across "
                    f"{len(self.config.test_centres)} centre(s)…")

        # Recover expired session (also handles closed browser window)
        if not await self.browser.is_session_valid():
            logger.warning("Session expired — re-logging in…")
            await self.browser.restart_page()
            ok = await self.browser.login()
            if not ok:
                logger.error("Re-login failed, skipping cycle.")
                return
            await self.browser.navigate_to_calendar()

        # If browser drifted to www.gov.uk or away from the portal, bring it back
        try:
            current_url = self.browser._page.url
            if "driver-services.dvsa.gov.uk" not in current_url:
                logger.warning(f"Browser is on wrong page ({current_url}) — re-navigating to calendar…")
                await self.browser.navigate_to_calendar()
        except Exception:
            pass

        # Make sure all configured centres appear on the calendar
        await self.browser.ensure_centres_on_page()

        # Scan every visible week
        try:
            all_slots = await self.browser.scan_all_weeks()
        except Exception as exc:
            logger.error(f"scan_all_weeks error: {exc}")
            all_slots = []

        await self._process_slots(all_slots)

    async def _process_slots(self, all_slots: list):
        now = datetime.now()
        current_keys: Set[str] = set()

        for slot in all_slots:
            key = self._slot_key(slot)
            current_keys.add(key)

            is_new = key not in self._known_slots
            last_alert = self._last_alerted.get(key)
            repeat_due = (
                last_alert is None or
                (now - last_alert).total_seconds() >= self.config.repeat_alert_interval
            )

            if is_new or repeat_due:
                if is_new:
                    logger.info(f"*** NEW SLOT: {slot['centre']} | {slot['date']} | {slot['time']} ***")
                    self._known_slots.add(key)
                else:
                    logger.info(f"Repeating alert for: {slot['centre']} | {slot['date']}")

                self._last_alerted[key] = now

                # Alert
                await self.notifier.send_slot_alert(slot)

                # Screenshot
                if self.config.save_screenshots:
                    try:
                        fname = (
                            f"{SCREENSHOT_DIR}/"
                            f"{slot['centre'].replace(' ', '_')}_"
                            f"{slot['date']}_{now.strftime('%H%M%S')}.png"
                        )
                        img_bytes = await self.browser.screenshot(path=fname)
                        await self.notifier.send_photo(img_bytes, caption=f"📸 {slot['centre']} — {slot['date']}")
                    except Exception as exc:
                        logger.warning(f"Screenshot failed: {exc}")

                # Pre-open the reservation page to save the user time
                try:
                    await self.browser.click_view_on_slot(slot)
                except Exception as exc:
                    logger.warning(f"Could not click View: {exc}")

        # Expire slots that have vanished
        gone = self._known_slots - current_keys
        for key in gone:
            logger.info(f"Slot gone: {key}")
            self._known_slots.discard(key)
            self._last_alerted.pop(key, None)

        if not current_keys:
            logger.info("No available slots found this cycle.")

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _slot_key(slot: dict) -> str:
        return f"{slot['centre']}|{slot['date']}|{slot['time']}"
