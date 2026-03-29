"""
browser.py — Playwright-based browser automation for the DVSA portal.

Real portal: driver-services.dvsa.gov.uk
Observed layout (sample.jpeg):
  Step 1 → Find available tests
  Step 2 → Test centre availability  ← This is the weekly calendar we monitor
  Step 3 → Add details to reserved tests
  Step 4 → Order details

The Step-2 calendar shows a grid:
  Rows    = test centres (e.g. Wolverhampton, Featherstone…)
  Columns = Mon – Sun with date numbers
  GREEN numbered cell  = available slots  ← we detect these
  Dark red / 0 cell    = no slots
  
We iterate "next week" until we reach date_range_days ahead, collecting
every green slot.  When found we open the reservation URL and alert the user.
"""
import asyncio
import json
import logging
import os
import random
import re
from calendar import month_abbr
from datetime import date as date_type, datetime, timedelta
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

logger = logging.getLogger(__name__)

# ── URLs ────────────────────────────────────────────────────────────────────
DVSA_LOGIN_URL   = "https://driver-services.dvsa.gov.uk/mot/login"
DVSA_PORTAL_HOME = "https://driver-services.dvsa.gov.uk"

# ── Selectors — matched to real driver-services.dvsa.gov.uk portal ──────────

# Login page
SEL_USERNAME    = "input#Username, input[name='Username'], input[type='text']"
SEL_PASSWORD    = "input#Password, input[name='Password'], input[type='password']"
SEL_LOGIN_BTN   = ("input[type='submit'][value='LOG IN'], "
                   "input[type='submit'], button[type='submit']")

# Step 2 calendar — next week navigation (multiple fallback selectors)
SEL_NEXT_WEEK   = (
    "a:has-text('next week'), "
    "a:has-text('Next week'), "
    "a:has-text('Next Week'), "
    "a[href*='NextWeek'], "
    "a[href*='next-week'], "
    "a[href*='nextWeek'], "
    "input[value*='Next'], "
    "button:has-text('Next')"
)
SEL_TABLE_ROWS  = "table tbody tr, table tr"

# Add test centre controls (bottom of Step 2 page)
SEL_ADD_CENTRE_SELECT = "select#TestCentreId, select[name='TestCentreId'], select"
SEL_ADD_CENTRE_BTN    = ("input[value*='Add'], input[value*='add'], "
                         "button:has-text('Add test centre')")


class DVSABrowser:
    """Manages a single Chromium browser session for monitoring DVSA slots."""

    def __init__(self, config):
        self.config = config
        self._pw = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._logged_in = False
        # Month abbreviation lookup built from stdlib calendar
        self._month_map = {v.lower(): i for i, v in enumerate(month_abbr) if v}

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self):
        """Launch the browser with anti-bot stealth settings."""
        self._pw = await async_playwright().start()

        # Use real Chrome locally (avoids Error 16), Playwright Chromium on cloud
        import os
        use_real_chrome = os.environ.get("DISPLAY", "local") == "local" and not os.environ.get("RENDER")

        launch_kwargs = dict(
            headless=self.config.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--start-maximized",
            ],
        )
        if use_real_chrome:
            try:
                self._browser = await self._pw.chromium.launch(channel="chrome", **launch_kwargs)
                logger.info("Using real Chrome browser.")
            except Exception:
                logger.warning("Real Chrome not found — falling back to Playwright Chromium.")
                self._browser = await self._pw.chromium.launch(**launch_kwargs)
        else:
            self._browser = await self._pw.chromium.launch(**launch_kwargs)
            logger.info("Using Playwright Chromium (cloud mode).")

        self._context = await self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-GB",
            timezone_id="Europe/London",
            java_script_enabled=True,
            has_touch=False,
            is_mobile=False,
            color_scheme="light",
            extra_http_headers={
                "Accept-Language": "en-GB,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        )

        # Comprehensive stealth — hides all automation indicators
        await self._context.add_init_script("""
            // Hide webdriver flag
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

            // Realistic plugins list
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    const p = [
                        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                        { name: 'Native Client', filename: 'internal-nacl-plugin' },
                    ];
                    p.__proto__ = PluginArray.prototype;
                    return p;
                }
            });

            // Language and platform
            Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en'] });
            Object.defineProperty(navigator, 'platform',  { get: () => 'Win32' });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
            Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });

            // Full Chrome object (Cloudflare checks for this)
            window.chrome = {
                runtime: {
                    connect: () => {},
                    sendMessage: () => {},
                    onMessage: { addListener: () => {} },
                },
                loadTimes: function() { return {}; },
                csi: function() { return {}; },
                app: { isInstalled: false },
            };

            // Remove Playwright indicators
            try { delete window.__playwright; } catch(e) {}
            try { delete window.__pw_manual; } catch(e) {}
            try { delete window._playwrightWorker; } catch(e) {}

            // Permissions API (real browsers have this)
            const origQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) =>
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : origQuery(parameters);
        """)

        self._page = await self._context.new_page()
        await self._load_cookies()
        logger.info("Browser started.")

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        logger.info("Browser closed.")

    # ── Authentication ────────────────────────────────────────────────────────

    async def login(self) -> bool:
        """Log in to driver-services.dvsa.gov.uk.  Returns True on success."""
        for attempt in range(1, 4):
            try:
                # Try cookie restore — go straight to the /mot/ booking section
                mot_home = f"{DVSA_PORTAL_HOME}/mot/"
                await self._page.goto(mot_home, wait_until="domcontentloaded", timeout=30_000)
                await self._human_delay(1.5, 2.5)

                if await self._is_logged_in():
                    logger.info("Session restored from cookies.")
                    self._logged_in = True
                    return True

                logger.info(f"Navigating to DVSA login page… (attempt {attempt})")
                await self._page.goto(DVSA_LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
                await self._human_delay(0.8, 1.5)

                # Username
                u_field = await self._page.wait_for_selector(SEL_USERNAME, timeout=15_000)
                await u_field.triple_click()
                await self._human_type(u_field, self.config.username)
                await self._human_delay(0.3, 0.7)

                # Password
                p_field = await self._page.wait_for_selector(SEL_PASSWORD, timeout=10_000)
                await p_field.click()
                await self._human_type(p_field, self.config.password)
                await self._human_delay(0.4, 0.9)

                # Submit
                btn = await self._page.query_selector(SEL_LOGIN_BTN)
                if btn:
                    await btn.click()
                else:
                    await p_field.press("Enter")

                await self._page.wait_for_load_state("domcontentloaded", timeout=25_000)
                await self._human_delay(1.5, 2.5)

                if await self._is_logged_in():
                    self._logged_in = True
                    await self._save_cookies()
                    logger.info("Logged in successfully.")
                    return True

                logger.error("Login failed — check credentials or solve CAPTCHA manually.")
                await self._page.screenshot(path="login_failed.png")
                return False

            except Exception as exc:
                logger.warning(f"Login attempt {attempt} error: {exc}")
                if attempt < 3:
                    await asyncio.sleep(5)
                else:
                    logger.error(f"Login failed after 3 attempts: {exc}")
                    try:
                        await self._page.screenshot(path="login_error.png")
                    except Exception:
                        pass
                    return False
        return False

    async def is_session_valid(self) -> bool:
        try:
            return await self._is_logged_in()
        except Exception:
            return False

    # ── Add test centres to the page ─────────────────────────────────────────

    async def navigate_to_calendar(self) -> bool:
        """
        Navigate from the DVSA portal dashboard to the Step-2 availability calendar.
        Stays strictly within driver-services.dvsa.gov.uk — any redirect to www.gov.uk
        is caught and reversed immediately.
        Returns True if we end up on a page containing the calendar table.
        """
        try:
            current_url = self._page.url
            logger.info(f"navigate_to_calendar: currently at {current_url}")

            # Already on the right page?
            if await self._page.query_selector(SEL_NEXT_WEEK):
                logger.info("Already on the calendar page.")
                return True

            # ── Detect Error 16 / Cloudflare block ───────────────────────────
            try:
                body_text = (await self._page.inner_text("body")).lower()
                if "error 16" in body_text or ("access denied" in body_text and "dvsa" in body_text):
                    logger.warning("DVSA is blocking us (Error 16). Clearing cookies and waiting 60s...")
                    await self._context.clear_cookies()
                    try:
                        import os
                        if os.path.exists(self.config.cookies_file):
                            os.remove(self.config.cookies_file)
                    except Exception:
                        pass
                    await asyncio.sleep(60)
                    await self._page.goto(DVSA_LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
                    await self._human_delay(3.0, 5.0)
                    current_url = self._page.url
            except Exception:
                pass

            # ── If landed on www.gov.uk, return to portal ─────────────────────
            if "www.gov.uk" in current_url or "driver-services.dvsa.gov.uk" not in current_url:
                logger.info("Not on driver-services portal — navigating back...")
                await self._page.goto(f"{DVSA_PORTAL_HOME}/mot/", wait_until="domcontentloaded", timeout=25_000)
                await self._human_delay(2.0, 3.5)
                current_url = self._page.url

            # Log all links on the portal home page for debugging
            try:
                all_links = await self._page.query_selector_all("a[href]")
                link_info = []
                for lnk in all_links[:30]:
                    txt = (await lnk.inner_text()).strip().replace("\n", " ")
                    href = (await lnk.get_attribute("href") or "")
                    if txt:
                        link_info.append(f"'{txt}' [{href}]")
                if link_info:
                    logger.info("Portal links: " + " | ".join(link_info))
            except Exception:
                pass

            # ── Try booking-related links — ONLY within driver-services ───────
            booking_keywords = [
                "book", "available", "test centre", "find test",
                "pupil", "candidate", "slot", "appointment", "search",
            ]
            all_links = await self._page.query_selector_all("a[href]")
            for lnk in all_links:
                try:
                    txt = (await lnk.inner_text()).strip().lower()
                    href = (await lnk.get_attribute("href") or "").lower()

                    # Skip any link that explicitly goes outside driver-services.dvsa.gov.uk
                    if href.startswith("http") and "driver-services.dvsa.gov.uk" not in href:
                        continue
                    # Explicitly skip gov.uk links (catches relative paths that include gov.uk)
                    if "www.gov.uk" in href:
                        continue

                    if not any(kw in txt or kw in href for kw in booking_keywords):
                        continue

                    logger.info(f"Clicking link: '{txt}' → {href}")
                    await lnk.click()
                    await self._page.wait_for_load_state("domcontentloaded", timeout=15_000)
                    await self._human_delay(0.8, 1.5)

                    # Check we haven't been redirected outside the portal
                    new_url = self._page.url
                    if "driver-services.dvsa.gov.uk" not in new_url:
                        logger.info(f"Redirected to {new_url} — going back to portal")
                        await self._page.goto(f"{DVSA_PORTAL_HOME}/mot/",
                                              wait_until="domcontentloaded", timeout=15_000)
                        await self._human_delay(0.5, 1.0)
                        continue

                    if await self._page.query_selector(SEL_NEXT_WEEK):
                        logger.info(f"Calendar reached at {self._page.url}")
                        return True

                    # Go one level deeper
                    inner_links = await self._page.query_selector_all("a[href]")
                    for il in inner_links:
                        il_txt = (await il.inner_text()).strip().lower()
                        il_href = (await il.get_attribute("href") or "").lower()
                        if il_href.startswith("http") and "driver-services.dvsa.gov.uk" not in il_href:
                            continue
                        if "www.gov.uk" in il_href:
                            continue
                        if any(kw in il_txt or kw in il_href for kw in booking_keywords):
                            await il.click()
                            await self._page.wait_for_load_state("domcontentloaded", timeout=15_000)
                            await self._human_delay(0.5, 1.0)
                            new_url2 = self._page.url
                            if "driver-services.dvsa.gov.uk" not in new_url2:
                                await self._page.goto(f"{DVSA_PORTAL_HOME}/mot/",
                                                      wait_until="domcontentloaded", timeout=15_000)
                                continue
                            if await self._page.query_selector(SEL_NEXT_WEEK):
                                logger.info(f"Calendar reached at {self._page.url}")
                                return True

                    # Back to portal home to try next link
                    await self._page.goto(f"{DVSA_PORTAL_HOME}/mot/",
                                          wait_until="domcontentloaded", timeout=15_000)
                    await self._human_delay(0.5, 1.0)
                except Exception:
                    continue

            logger.warning(
                f"Could not navigate to the availability calendar automatically.\n"
                f">>> ACTION NEEDED: In the browser window that is open, manually:\n"
                f"    1. Log in to driver-services.dvsa.gov.uk\n"
                f"    2. Navigate to 'Find available tests' / the weekly calendar\n"
                f"    The bot will automatically detect the calendar on the next check "
                f"(every {self.config.refresh_interval}s) and start monitoring."
            )
            return False
        except Exception as exc:
            logger.error(f"navigate_to_calendar error: {exc}")
            return False

    async def ensure_centres_on_page(self):
        """
        On Step 2 the portal shows up to 5 centres.
        Use the 'Add another test centre' dropdown to add any missing ones.
        """
        try:
            for centre in self.config.test_centres:
                body = await self._page.inner_text("body")
                if centre.lower() in body.lower():
                    continue  # already visible

                sel_el = await self._page.query_selector(SEL_ADD_CENTRE_SELECT)
                if not sel_el:
                    break

                options = await sel_el.query_selector_all("option")
                for opt in options:
                    label = (await opt.inner_text()).strip().lower()
                    if centre.lower() in label:
                        val = await opt.get_attribute("value")
                        await sel_el.select_option(value=val)
                        add_btn = await self._page.query_selector(SEL_ADD_CENTRE_BTN)
                        if add_btn:
                            await add_btn.click()
                            await self._page.wait_for_load_state("domcontentloaded", timeout=10_000)
                            await self._human_delay(0.5, 1.0)
                        break
        except Exception as exc:
            logger.warning(f"ensure_centres_on_page: {exc}")

    # ── Full multi-week scan ──────────────────────────────────────────────────

    async def scan_all_weeks(self) -> list:
        """
        Iterate the Step-2 weekly calendar clicking 'next week' until we reach
        date_range_days ahead.  Returns all detected green slot dicts.
        """
        all_slots   = []
        deadline    = date_type.today() + timedelta(days=self.config.date_range_days)
        max_weeks   = (self.config.date_range_days // 7) + 2
        weeks_done  = 0

        while weeks_done < max_weeks:
            week_slots = await self._scan_current_week()
            all_slots.extend(week_slots)
            weeks_done += 1

            if week_slots:
                latest = max(s["date"] for s in week_slots)
                if latest >= deadline:
                    break

            # Try structured selector first
            next_btn = await self._page.query_selector(SEL_NEXT_WEEK)

            # Try structured selector first
            next_btn = await self._page.query_selector(SEL_NEXT_WEEK)

            # Fallback 1: JavaScript link text search (catches any casing/spacing)
            if not next_btn:
                try:
                    next_btn = await self._page.evaluate_handle("""
                        () => {
                            const els = [...document.querySelectorAll('a, button, input')];
                            return els.find(el => {
                                const t = (el.innerText || el.value || '').trim().toLowerCase();
                                return t.includes('next week') || t === 'next';
                            }) || null;
                        }
                    """)
                    # evaluate_handle returns JSHandle — check if it's actually an element
                    val = await next_btn.json_value()
                    if val is None:
                        next_btn = None
                    else:
                        logger.info("Found next-week button via JavaScript search.")
                except Exception:
                    next_btn = None

            # Fallback 2: log all link texts for debugging
            if not next_btn:
                try:
                    all_links_text = await self._page.evaluate("""
                        () => [...document.querySelectorAll('a, button')]
                              .map(el => (el.innerText || '').trim())
                              .filter(t => t.length > 0 && t.length < 30)
                              .slice(0, 20)
                    """)
                    logger.info(f"Page links (debug): {all_links_text}")
                except Exception:
                    pass

            if not next_btn:
                logger.info("No 'next week' link — reached end of calendar.")
                break

            try:
                await next_btn.click()
                await self._page.wait_for_load_state("domcontentloaded", timeout=15_000)
                await self._human_delay(0.8, 1.5)
            except Exception as exc:
                logger.warning(f"Could not click next week: {exc}")
                break

        logger.info(f"Scanned {weeks_done} week(s) — {len(all_slots)} slot(s) found.")
        return all_slots

    async def _scan_current_week(self) -> list:
        """
        Parse the current Step-2 calendar page.

        Grid structure (from sample.jpeg):
          thead:  | Test centre and category | Mon 13 | Tue 14 | … | Sun 19 |
          tbody:  | Featherstone\\nCar        |  <a>0  |  <a>0  | … |
                  | Wolverhampton\\nCar       |  <a>0  |  <a>0  | … |

        A cell is 'available' when its <a> contains a positive integer.
        We also do a JS background-colour check to confirm green.
        """
        slots = []

        # --- Extract column dates from header ---
        col_dates: list = []
        try:
            page_heading = ""
            h = await self._page.query_selector("h1, h2, .heading-large")
            if h:
                page_heading = (await h.inner_text()).strip()

            header_cells = await self._page.query_selector_all(
                "table thead tr th, table tr:first-child th, table tr:first-child td"
            )
            for cell in header_cells[1:]:  # skip "Test centre" column
                d = await self._header_cell_to_date(cell, page_heading)
                col_dates.append(d)
        except Exception as exc:
            logger.debug(f"Header parse error: {exc}")

        # --- Scan data rows ---
        try:
            rows = await self._page.query_selector_all(SEL_TABLE_ROWS)
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 2:
                    continue

                # First cell = centre name
                raw = (await cells[0].inner_text()).strip()
                centre_name = raw.split("\n")[0].strip()
                if not centre_name or "test centre" in centre_name.lower():
                    continue
                if not self._centre_matches(centre_name):
                    continue

                for col_idx, cell in enumerate(cells[1:]):
                    link = await cell.query_selector("a")
                    if not link:
                        continue

                    count_text = (await link.inner_text()).strip()
                    if not count_text.isdigit() or int(count_text) <= 0:
                        continue

                    count = int(count_text)

                    # JS background-colour check (green = available)
                    try:
                        is_green = await self._page.evaluate(
                            """el => {
                                const s = window.getComputedStyle(el);
                                const bg = s.backgroundColor + s.background;
                                return bg.includes('0, 128') || bg.includes('0, 153') ||
                                       bg.includes('34, 139') || bg.includes('green') ||
                                       bg.includes('0, 170') || bg.includes('0, 100');
                            }""",
                            cell
                        )
                    except Exception:
                        is_green = True  # assume valid if JS check fails

                    # Accept any linked positive-count cell (green check is advisory)
                    slot_date = col_dates[col_idx] if col_idx < len(col_dates) else None
                    if slot_date is None:
                        href = await link.get_attribute("href") or ""
                        slot_date = self._parse_date(href) or date_type.today()

                    if not self._within_range(slot_date):
                        continue

                    link_href = await link.get_attribute("href") or ""
                    slots.append({
                        "centre": centre_name,
                        "date": slot_date,
                        "slot_count": count,
                        "time": "any",
                        "text": f"{count} slot(s) — {centre_name} {slot_date}",
                        "page_url": self._page.url,
                        "_link_href": link_href,
                        "_link_element": link,
                        "_is_green": is_green,
                    })

        except Exception as exc:
            logger.error(f"_scan_current_week error: {exc}")

        return slots

    async def _header_cell_to_date(self, cell, page_heading: str) -> Optional[date_type]:
        """Convert a header TH like 'Mon\n13' + page heading month/year → date."""
        try:
            text = (await cell.inner_text()).strip()
            day_m = re.search(r"(\d{1,2})", text)
            if not day_m:
                return None
            day = int(day_m.group(1))

            # Extract month + year from heading:
            # "Number of available tests between 13th Apr 2026 – 19th Apr 2026"
            m = re.search(r"(\d{1,2})[a-z]*\s+([A-Za-z]+)\s+(\d{4})", page_heading)
            if m:
                month = self._month_map.get(m.group(2)[:3].lower())
                year  = int(m.group(3))
                if month:
                    # Handle month rollover (e.g. week spans Dec→Jan)
                    try:
                        return date_type(year, month, day)
                    except ValueError:
                        # day out of range for that month → next month
                        if month == 12:
                            return date_type(year + 1, 1, day)
                        return date_type(year, month + 1, day)
        except Exception:
            pass
        return None

    # ── Slot booking page ─────────────────────────────────────────────────────

    async def open_slot_booking_page(self, slot: dict) -> bool:
        """Navigate to the reservation page for <slot> (Step 3)."""
        try:
            href = slot.get("_link_href", "")
            if href:
                url = href if href.startswith("http") else f"{DVSA_PORTAL_HOME}{href}"
                await self._page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                logger.info(f"Opened booking page: {slot['centre']} {slot['date']}")
                return True
            el = slot.get("_link_element")
            if el:
                await el.click()
                await self._page.wait_for_load_state("domcontentloaded", timeout=15_000)
                return True
        except Exception as exc:
            logger.error(f"open_slot_booking_page: {exc}")
        return False

    # Compatibility aliases for monitor.py
    async def check_centre_availability(self, centre: str) -> list:
        week = await self._scan_current_week()
        return [s for s in week if centre.lower() in s["centre"].lower()]

    async def click_view_on_slot(self, slot: dict) -> bool:
        return await self.open_slot_booking_page(slot)

    async def screenshot(self, path: Optional[str] = None) -> bytes:
        data = await self._page.screenshot(full_page=False)
        if path:
            Path(path).write_bytes(data)
        return data

    # ── Cookie persistence ────────────────────────────────────────────────────

    async def _save_cookies(self):
        try:
            cookies = await self._context.cookies()
            with open(self.config.cookies_file, "w") as f:
                json.dump(cookies, f)
            logger.debug("Session cookies saved.")
        except Exception as exc:
            logger.warning(f"Could not save cookies: {exc}")

    async def _load_cookies(self):
        path = self.config.cookies_file
        if not os.path.exists(path):
            return
        try:
            with open(path, "r") as f:
                cookies = json.load(f)
            await self._context.add_cookies(cookies)
            logger.debug("Session cookies loaded.")
        except Exception as exc:
            logger.warning(f"Could not load cookies: {exc}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _is_logged_in(self) -> bool:
        url = self._page.url.lower()
        if "login" in url or "sign-in" in url:
            return False
        # Accept any DVSA-related page as logged-in
        if "dvsa.gov.uk" in url or "driver-services" in url:
            try:
                body = (await self._page.inner_text("body")).lower()
            except Exception:
                return False
            # If we see a login form, we're definitely not logged in
            if "log in" in body and "log out" not in body and "sign out" not in body:
                return False
            return True
        # We may have navigated elsewhere — use cached flag
        return self._logged_in

    async def restart_page(self):
        """Create a fresh page if the current one was closed."""
        try:
            _ = self._page.url  # will raise if page closed
        except Exception:
            logger.info("Page was closed — opening new page.")
            self._page = await self._context.new_page()
            self._logged_in = False

    async def _human_delay(self, lo: float, hi: float):
        await asyncio.sleep(random.uniform(lo, hi))

    async def _human_type(self, element, text: str):
        for char in text:
            await element.type(char)
            await asyncio.sleep(random.uniform(0.05, 0.13))

    def _centre_matches(self, name: str) -> bool:
        nl = name.lower()
        return any(c.lower() in nl or nl in c.lower() for c in self.config.test_centres)

    def _within_range(self, d: date_type) -> bool:
        today = date_type.today()
        return today <= d <= today + timedelta(days=self.config.date_range_days)

    _DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y"]

    def _parse_date(self, text: str) -> Optional[date_type]:
        for pat in (r"(\d{4})-(\d{2})-(\d{2})", r"(\d{1,2})/(\d{1,2})/(\d{4})"):
            m = re.search(pat, text)
            if m:
                a, b, c = m.groups()
                for fmt, val in (("%Y-%m-%d", f"{a}-{b}-{c}"), ("%d/%m/%Y", f"{a}/{b}/{c}")):
                    try:
                        return datetime.strptime(val, fmt).date()
                    except ValueError:
                        pass
        for fmt in self._DATE_FORMATS:
            try:
                return datetime.strptime(text.strip(), fmt).date()
            except ValueError:
                pass
        return None
