FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    TRACKFUND_DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY trackfund ./trackfund
COPY seed ./seed

RUN useradd --system --uid 10001 trackfund && mkdir -p /data && chown trackfund /data
USER trackfund
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

# one worker: the audit chain and ingestion are serialised in-process (Postgres advisory lock covers the audit chain)
CMD ["uvicorn", "trackfund.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
