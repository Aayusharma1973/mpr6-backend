# ── Stage: builder ───────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# System deps for Pillow, bcrypt, and Tesseract OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
        libssl-dev \
        tesseract-ocr \
        tesseract-ocr-eng \
        libtesseract-dev \
        libleptonica-dev \
        libpng-dev \
        libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /install
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install/pkg --no-cache-dir -r requirements.txt


# ── Stage: runtime ────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Only runtime libs — no compiler toolchain
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libpng-dev \
        libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /install/pkg /usr/local

# Copy application source
COPY . .

# Create directories that the app needs at runtime
RUN mkdir -p /app/logs
RUN mkdir -p /app/data /app/logs

# Non-root user for security
RUN useradd -m -u 1001 rxguardian && \
    mkdir -p /app/data /app/logs && \
    chown -R rxguardian:rxguardian /app
USER rxguardian

EXPOSE 8000

# Health-check so docker-compose knows when the service is ready
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
