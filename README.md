# DVSA Pupil Test Slot Monitor — Option 2 (Enhanced Assistant Bot)

## What it does

| Feature | Detail |
|---|---|
| **Monitors** | Up to 5 DVSA test centres simultaneously |
| **Refresh** | Every ~25 seconds (configurable) |
| **Alerts** | Telegram message + screenshot + Windows beep |
| **WhatsApp** | Optional (via Twilio) |
| **Session** | Cookies saved — no re-login on each run |
| **Pre-opens** | Clicks "View" on the slot so the booking page is ready for you |
| **You do** | Final confirm/reserve click only |

---

## Quick Start (Windows)

### Step 1 — Install Python
Download Python 3.11+ from <https://www.python.org/downloads/>  
**Tick "Add Python to PATH"** during install.

### Step 2 — Run Setup
Double-click `setup.bat`  
This installs all dependencies and the Chromium browser automatically.

### Step 3 — Configure

#### a) Credentials — edit `.env`
```
DVSA_USERNAME=246853988044
DVSA_PASSWORD=your_password_here
```
> ⚠️ Never share your `.env` file with anyone.

#### b) Test centres — edit `config.json`
```json
"test_centres": [
    "Birmingham",
    "Coventry",
    "Solihull",
    "Wolverhampton",
    "Dudley"
]
```
Replace with the 3–5 centres you actually want to monitor.

#### c) Date range & time preference — also in `config.json`
```json
"date_range_days": 90,
"time_preference": "any"
```
- `date_range_days` — how far ahead to look (90 = 3 months)
- `time_preference` — `"morning"`, `"afternoon"`, or `"any"`

### Step 4 — Set up Telegram alerts (recommended, free)

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` — follow the prompts
3. Copy the **token** it gives you
4. Start a chat with your new bot (just send `/start`)
5. Visit this URL in a browser (replace TOKEN):  
   `https://api.telegram.org/botTOKEN/getUpdates`  
   Find your **`id`** inside the `"chat"` object — that is your Chat ID
6. Paste both into `.env`:
```
TELEGRAM_BOT_TOKEN=1234567890:ABCdef...
TELEGRAM_CHAT_ID=987654321
```

### Step 5 — Run the monitor
```cmd
python main.py
```

The browser window will open (visible by default so you can watch it).  
Leave it running in the background and wait for an alert.

---

## WhatsApp alerts (optional — requires Twilio)

1. Sign up at <https://www.twilio.com>
2. Enable the **WhatsApp Sandbox** in the Twilio console
3. Fill in the Twilio values in `.env`:
```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_WHATSAPP_FROM=+14155238886
WHATSAPP_TO_NUMBER=+447XXXXXXXXX
```

---

## File overview

```
driving_system_bot/
├── main.py          ← Run this
├── monitor.py       ← Core check loop
├── browser.py       ← Playwright browser automation
├── notifier.py      ← Telegram / WhatsApp / sound alerts
├── config.py        ← Loads settings
├── config.json      ← Your preferences (centres, range, timing)
├── .env             ← Your secrets (NEVER share this)
├── .env.example     ← Template for .env
├── requirements.txt ← Python packages
├── setup.bat        ← One-click Windows setup
├── cookies.json     ← Session cookies (auto-created, keeps you logged in)
└── screenshots/     ← Auto-saved screenshots when slots are found
```

---

## Adjusting refresh speed

Edit `config.json`:
```json
"refresh_interval_seconds": 25
```
Lower = faster detection but higher chance of being rate-limited.  
**25–30 seconds** is a safe balance.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Browser shows CAPTCHA | Run with `"headless": false` (default) and solve it once; cookies are then saved |
| "Login failed" | Double-check username (no spaces) and password in `.env` |
| No Telegram messages | Confirm token and chat_id; make sure you started a conversation with your bot |
| Slots not detected | The portal may have changed its HTML — check `browser.py` selectors and update `SEL_AVAILABLE_SLOT` |
| Session keeps expiring | Delete `cookies.json` and let the bot log in fresh |

---

## Disclaimer

This tool is a **monitoring and alert assistant** only.  
You complete the final booking step yourself.  
Use responsibly in accordance with DVSA's Terms of Service.
