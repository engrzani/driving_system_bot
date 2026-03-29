# DVSA Slot Monitor — Docker image for cloud deployment (Render / Railway)
FROM python:3.11-slim

# Install system dependencies for Playwright + Chromium
RUN apt-get update && apt-get install -y \
    wget curl gnupg ca-certificates \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libatspi2.0-0 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright + Chromium
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy project files (credentials come via env vars — NOT copied)
COPY browser.py config.py monitor.py notifier.py main.py config.json ./
RUN mkdir -p screenshots

# Headless must be true in cloud (no display) — build v2
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=""

CMD ["python", "main.py"]
