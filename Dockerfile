# Kvasir — single container, single process, state only under /data.
FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/morphem/kvasir"
LABEL org.opencontainers.image.description="Kvasir — which AI agent to start, from three live sources"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    KVASIR_DATA_DIR=/data \
    KVASIR_WEB_DIR=/app/web \
    KVASIR_PORT=8688

WORKDIR /app

COPY pyproject.toml README.md ./
COPY kvasir ./kvasir
RUN pip install --no-cache-dir .

COPY web ./web

# Unraid's appdata is owned by nobody:users; the container runs as the same pair so the
# SQLite archive survives a container rebuild with its permissions intact.
RUN mkdir -p /data && chown -R 99:100 /data /app
VOLUME ["/data"]
EXPOSE 8688
USER 99:100

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8688/api/health', timeout=8).status == 200 else 1)"

CMD ["uvicorn", "kvasir.api:app", "--host", "0.0.0.0", "--port", "8688"]
