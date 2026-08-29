# Private-beta relay deployment handoff

The repository contains the complete beta relay/room-authority service. The hosting operator owns the
machine, DNS, TLS certificate, backups, alerts, and final public URL; those credentials never belong in
this repository.

## Start a staging instance

From a clean checkout at the committed beta revision:

```bash
docker compose -f relay/compose.yaml build --pull
docker compose -f relay/compose.yaml up -d
curl --fail http://127.0.0.1:8788/health
```

The Compose file binds only host loopback. Put a TLS ingress on the same host in front of it, proxy
HTTP and WebSocket upgrades to `127.0.0.1:8788`, and expose only the ingress. Keep exactly one relay
container/worker for this beta: authoritative room state is persisted in SQLite, while live RFU
WebSocket peers are deliberately process-local. Horizontal replicas require a later shared live-peer
router and are not safe merely by mounting the same database.

The reference and production-target deployment is the pinned container above. The current validation
host is a documented exception: it runs one launchd-supervised native uvicorn process. Native
validation may provide behavioral milestone evidence only when its committed source hashes, pinned
Python/dependency set, supervisor configuration, environment, persistent storage, and rollback
artifact are recorded. Two source-file hashes alone are not a reproducible production artifact.
Before production cutover, either deploy the reference container or commit and verify the complete
native release manifest; do not describe a native process as having passed a Docker image check.

Production mode sets `SWITCHTRADE_ENABLE_LEGACY_RELAY=0`. This is security-critical: the old
unauthenticated `/session/create` development API then returns 404, while the authenticated
`/v1/trade-rooms*` authority and credentialed RFU WebSockets remain enabled. Do not override it on a
public host.

## Hosting boundary

The relay container exposes HTTP on port 8788 only to a trusted TLS reverse proxy or managed
container ingress. The public URL must be `https://`; WebSocket upgrades must be enabled. Do not
publish port 8788 directly to the internet.

Required production controls:

- mount `/var/lib/switchtrade` on an encrypted persistent volume with backups restricted to the
  relay operator;
- retain the redacted diagnostic uploads under `/var/lib/switchtrade/diagnostics` according to the
  operator's support policy and restrict access to support staff;
- terminate TLS 1.2 or newer at the ingress and redirect plain HTTP before it reaches the service;
- limit request bodies at the ingress to 64 KiB for control requests, 16 MiB for
  `/v1/diagnostics/*`, and 1,048,832 bytes for RFU WebSocket messages;
- probe `/health`; collect `/metrics` only on the private operator network;
- retain structured operational logs for 14 days and exclude `Authorization` and WebSocket headers;
- alert on repeated 5xx responses, abnormal 429 rates, authority-volume exhaustion, and restart loops;
- preserve the SQLite volume across ordinary relay restarts so room seats and ordered events survive;
- deploy at least one staging instance and run the two-NAT qualification before promoting its signed
  `https://` URL into `payload/release-config.json`.
- apply ingress rate limits to room creation/join, reconnect, and WebSocket handshakes in addition to
  the service's per-client/member limits;
- use one worker and one replica for beta, mount the named `authority` volume, and test restore from a
  backup before promotion;
- restrict `/metrics` at the ingress. `/health` may be used by the platform probe but should not be
  treated as authentication.

The production endpoints are:

- `GET /health` — readiness and contract identity;
- `GET /metrics` — private operational counters;
- `POST /v1/diagnostics/support-bundle|hardware-diagnostic` — bounded, validated redacted support
  uploads stored outside the room database;
- `/v1/trade-rooms*` — authenticated authoritative room control;
- `POST /v2/trade-rooms/{room_id}/ready` — binds one redacted `p0-attestation.v2` and explicit
  Switch role to the member before the relay can admit a v2 attempt;
- `/v2/trade-rooms/{room_code}/attempts/{attempt_id}/ws` — credentialed, P0/attempt/launch-bound
  `rfu-tunnel.v2` transport. The caller sends its member bearer token plus run, stage generation,
  launch nonce, and endpoint PID headers. Seat comes only from the credential.

Before handing the URL to the packaging agent, run the repository test suite and the credentialed
hosting smoke:

```bash
python -m relay.smoke https://relay.example.invalid
```

The smoke verifies that `POST /session/create` returns 404, creates and joins an authoritative room,
admits two distinct matching P0 attestations, locks complementary roles, proves both v2 directions
with unpredictable nonces, delivers the exact fixture advertisement by hash, and closes the room.
Separately restart the container during a staged connection and confirm the attempt fails explicitly
with no retained v2 namespace. Then provide only the public
`https://` base URL; `installer/Build-Package.ps1 -Release` writes it into the signed configuration and
rejects HTTP or loopback release URLs.

The relay forwards validated RFU envelopes as opaque bytes. It does not import the decoder, retain RFU
payloads, or expose a committed-trade/analytics endpoint. Privacy, consent, and analytics services are
intentionally outside this repository/client implementation per owner direction.

Incident response: remove the affected relay URL from release configuration, preserve operational
logs and the encrypted authority volume, rotate deployment credentials, deploy a fixed image, and
invalidate active rooms by moving the compromised database out of service. Member and reconnect
credentials are stored only as SHA-256 hashes and are never logged.
