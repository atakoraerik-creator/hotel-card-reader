FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOORCARD_WEB_ENV=production \
    DOORCARD_WEB_HOST=0.0.0.0 \
    DOORCARD_WEB_PORT=8000 \
    DOORCARD_DATABASE_URL=sqlite:////app/data/doorcard-web.db \
    DOORCARD_SEED_DEMO=false \
    DOORCARD_ENCODER_MODE=simulated

WORKDIR /app

COPY requirements-web.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements-web.txt

COPY doorcard ./doorcard

RUN useradd --create-home --uid 10001 doorcard \
    && mkdir -p /app/data \
    && chown -R doorcard:doorcard /app/data

USER doorcard

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

CMD ["python", "-m", "doorcard.web"]
