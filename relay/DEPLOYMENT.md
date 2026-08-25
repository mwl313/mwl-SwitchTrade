# Private-beta relay deployment

The relay container exposes HTTP on port 8788 only to a trusted TLS reverse proxy or managed
container ingress. The public URL must be `https://`; WebSocket upgrades must be enabled. Do not
publish port 8788 directly to the internet.

Required production controls:

- mount `/var/lib/switchtrade` on an encrypted persistent volume with backups restricted to the
  relay operator;
- terminate TLS 1.2 or newer at the ingress and redirect plain HTTP before it reaches the service;
- limit request bodies at the ingress to 64 KiB for control requests and 1,048,832 bytes for RFU
  WebSocket messages;
- probe `/health`; collect `/metrics` only on the private operator network;
- retain structured operational logs for 14 days and exclude `Authorization` and WebSocket headers;
- alert on repeated 5xx responses, abnormal 429 rates, authority-volume exhaustion, and restart loops;
- preserve the SQLite volume across ordinary relay restarts so room seats and ordered events survive;
- deploy at least one staging instance and run the two-NAT qualification before promoting its signed
  `https://` URL into `payload/release-config.json`.

The relay forwards validated RFU envelopes as opaque bytes. It does not import the decoder, retain RFU
payloads, or expose a committed-trade/analytics endpoint. Privacy, consent, and analytics services are
intentionally outside this repository/client implementation per owner direction.

Incident response: remove the affected relay URL from release configuration, preserve operational
logs and the encrypted authority volume, rotate deployment credentials, deploy a fixed image, and
invalidate active rooms by moving the compromised database out of service. Member and reconnect
credentials are stored only as SHA-256 hashes and are never logged.
