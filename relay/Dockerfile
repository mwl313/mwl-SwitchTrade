FROM python:3.12.11-slim@sha256:0b29ab9e420820f53d1cd5ce0157dfe07bea8a7cff5b4754d6d95c07b0e5bc47

ARG SWITCHTRADE_RELAY_REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/mwl313/mwl-SwitchTrade" \
      org.opencontainers.image.revision=$SWITCHTRADE_RELAY_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SWITCHTRADE_RELAY_REVISION=$SWITCHTRADE_RELAY_REVISION
WORKDIR /srv/switchtrade
COPY relay/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes --requirement /tmp/requirements.txt \
    && useradd --system --uid 10001 --create-home switchtrade
COPY --chown=switchtrade:switchtrade relay/core_server.py relay/core_contracts.py relay/pair_store.py relay/
COPY --chown=switchtrade:switchtrade switchtrade/__init__.py switchtrade/VERSION switchtrade/
COPY --chown=switchtrade:switchtrade switchtrade/core switchtrade/core
COPY --chown=switchtrade:switchtrade switchtrade/transport switchtrade/transport
USER 10001
EXPOSE 8788
CMD ["uvicorn", "relay.core_server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8788", "--workers", "1", "--proxy-headers", "--ws-max-size", "1048832", "--ws-max-queue", "8", "--timeout-keep-alive", "10", "--timeout-graceful-shutdown", "10", "--no-access-log", "--log-level", "warning"]
