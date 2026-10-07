##############################################
# Daleel Pets — Backend Dockerfile
# FastAPI + Playwright + Chromium
##############################################
FROM python:3.11-slim

# System deps for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg ca-certificates fonts-noto-color-emoji \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 libx11-xcb1 \
    libxcomposite1 libxdamage1 libxrandr2 libatspi2.0-0 libcups2 \
    && rm -rf /var/lib/apt/lists/*

# Arabic font support
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-core fonts-noto-cjk fonts-arabeyes \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium only)
ENV PLAYWRIGHT_BROWSERS_PATH=/pw-browsers
RUN playwright install chromium && playwright install-deps chromium

# Copy application code
COPY backend/ ./

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8001/api/health || exit 1

# Run with uvicorn
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
