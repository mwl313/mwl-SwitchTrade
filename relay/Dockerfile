FROM python:3.12.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SWITCHTRADE_AUTH_DB=/var/lib/switchtrade/authority.sqlite3 \
    SWITCHTRADE_ENABLE_LEGACY_RELAY=0
WORKDIR /srv/switchtrade
COPY relay/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --requirement /tmp/requirements.txt \
    && useradd --system --uid 10001 --create-home switchtrade \
    && install -d -o switchtrade -g switchtrade /var/lib/switchtrade
COPY --chown=switchtrade:switchtrade relay relay
COPY --chown=switchtrade:switchtrade switchtrade switchtrade
USER 10001
EXPOSE 8788
CMD ["uvicorn", "relay.server:app", "--host", "0.0.0.0", "--port", "8788", "--workers", "1", "--no-proxy-headers", "--ws-max-size", "1048832", "--timeout-keep-alive", "10"]
