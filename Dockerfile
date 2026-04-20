# ════════════════════════════════════════════════════════════════════════════
#  RxGuardian — Dockerfile
#
#  Base image: pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime
#    ↳ This is the closest official pytorch image to what r1.txt used
#      (torch==2.11.0+cu130). cu130 wheels install on top of a cu12.x base fine.
#
#  CRITICAL: --extra-index-url must be cu130, not cu121.
#    torch==2.11.0+cu130 / torchvision==0.26.0+cu130 are the EXACT versions
#    confirmed working from the r1.txt pip freeze.
# ════════════════════════════════════════════════════════════════════════════

FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TOKENIZERS_PARALLELISM=false \
    BITSANDBYTES_NOWELCOME=1 \
    HF_HUB_DISABLE_PROGRESS_BARS=0
# TRANSFORMERS_VERBOSITY=error \

# System libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    libssl-dev \
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev \
    libleptonica-dev \
    libpng-dev \
    libjpeg-dev \
    libgomp1 \
    curl \
    wget \
    gnupg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome for Selenium
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/googlechrome-linux-keyring.gpg \
    && sh -c 'echo "deb [arch=amd64 signed-by=/usr/share/keyrings/googlechrome-linux-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list' \
    && apt-get update \
    && apt-get install -y google-chrome-stable --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Install into the conda env Python uses.
# --extra-index-url cu130 matches torch==2.11.0+cu130 in requirements.txt.
RUN pip install --upgrade pip && \
    pip install \
    --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cu130 \
    -r requirements.txt

# Copy app source AFTER pip so source edits don't bust the layer cache
COPY . .

RUN mkdir -p /app/data /app/logs

# Non-root user — pre-create the HF cache dir HERE (as root) before the
# volume is mounted, so it's owned by rxguardian. Without this, Docker
# creates the volume mount as root → PermissionError when HF tries to write.
RUN useradd -m -u 1001 rxguardian && \
    mkdir -p /home/rxguardian/.cache/huggingface && \
    chown -R rxguardian:rxguardian /app /home/rxguardian
USER rxguardian

EXPOSE 8000

# Long start-period: Qwen2-VL-2B takes ~30-60 s to load into VRAM
HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=120s \
    --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Single worker — model lives in one process's GPU memory.
CMD ["uvicorn", "app.main:app", \
    "--host", "0.0.0.0", \
    "--port", "8000", \
    "--workers", "1"]