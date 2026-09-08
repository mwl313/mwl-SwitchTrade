# Simple Architecture Core relay — deployment agent handoff

Deploy this repository's **`codex/gpsp-endpoint`** branch at its reviewed exact SHA.
Do not deploy `main`, an older release/tag, or `relay.server:app`. The canonical
server is **`relay.core_server:create_app --factory`**. Default Docker/Compose now
selects it. This document prepares deployment; it is not evidence of a live cutover.

## Service contract

| Route | Purpose |
| --- | --- |
| `GET /core/health` | Service/contract/build identity, not functional readiness |
| `POST /core/v1/pairs` | Host creates a six-digit Pair code and private credential |
| `POST /core/v1/pairs:join` | Guest consumes the code and receives its own credential |
| `GET /core/v1/pairs/{pair_id}` | Read-only status; bearer credential required |
| `WS /core/v1/pairs/{pair_id}/ws` | Binary Core envelopes; bearer credential determines seat |

Same service for Switch↔Switch and Switch↔gpSP. Payloads remain opaque; no LDN,
RFU translation, emulator, radio, game keys, Room browser, Ready, Continue,
SQLite, diagnostics upload, or user account service belongs in this deployment.
Old `/health`, `/v1/trade-rooms*`, `/session/create`, and legacy RFU routes are
not aliases and must not be used as Core readiness evidence.

**Exactly one process/worker and one replica.** Pair/socket state is in memory.
Restart/update/rollback drops all Pairs, including credentials and codes; users
must restart their Host/Join session with a new code. A normal game Generation
ending does not restart the relay or discard the Pair. No shared-volume or
rolling-replica workaround is supported. Current limits: 128 Pairs, ten-minute
unconsumed code lifetime, one-hour reconnect admission lease. Existing attached
streams are not a one-hour game timer. Create/join/guess limits are per client IP;
HTTP connection keepalive and WebSocket ping timers are not human-wait deadlines.

## Pre-deployment checks (operator-owned)

1. Record the active service manager/process identity, listening port, source or
   image digest, ingress config, and rollback artifact. Do not infer these from a
   404. An existing launchd/systemd process must not compete with Docker on 8788.
2. Preserve the old service's SQLite volume, logs and credentials privately.
   Do not run `docker compose down -v`, remove volumes, or migrate Room data into Core.
3. Fetch the feature branch into a clean dedicated checkout. Record the literal
   40-character SHA (`git rev-parse HEAD`) and `git status --porcelain`; abort on
   unexpected edits. Review the CI for that SHA; a previously green SHA is not proof.
4. Stage Core on a separate operator-selected listener/hostname before replacing
   the old public route. Existing legacy desktop clients are not Core clients;
   coordinate their cutover or retain their service at a separate hostname.

## Reference deployment: Docker Compose

From the repository root on the deployment host:

```bash
export SWITCHTRADE_RELAY_REVISION="$(git rev-parse HEAD)"
# Set the actual immediate proxy IP as observed by the CONTAINER, not its public DNS IP.
# For a host proxy this is commonly the Docker bridge gateway; inspect, do not guess.
export SWITCHTRADE_RELAY_TRUSTED_PROXIES='<verified-ingress-IP>'
docker compose -p switchtrade-core -f relay/compose.yaml config
docker compose -p switchtrade-core -f relay/compose.yaml build --pull
docker compose -p switchtrade-core -f relay/compose.yaml up -d
docker compose -p switchtrade-core -f relay/compose.yaml ps
curl --fail http://127.0.0.1:8788/core/health
```

Replace the placeholder before execution. Compose refuses missing revision/proxy
settings. The image label and health `source_revision` record the supplied SHA;
they are build labels, **not an independent content signature**. Build only the
verified clean checkout and record the resulting image ID/digest. Core runs as
UID 10001, read-only, with no host mounts or privileges. Published 8788 is host
loopback only. A TLS ingress is mandatory for Internet use.

## Alternative: existing native service manager

Use a dedicated Python 3.12 virtualenv and the same clean source SHA, without
installing client/hardware dependencies:

```bash
python3.12 -m venv .relay-venv
.relay-venv/bin/python -m pip install --require-hashes -r relay/requirements.txt
.relay-venv/bin/python -m pip check
export SWITCHTRADE_RELAY_REVISION="$(git rev-parse HEAD)"
export FORWARDED_ALLOW_IPS=127.0.0.1
.relay-venv/bin/python -m uvicorn relay.core_server:create_app --factory \
  --host 127.0.0.1 --port 8788 --workers 1 --proxy-headers \
  --ws-max-size 1048832 --ws-max-queue 8 --timeout-keep-alive 10 \
  --timeout-graceful-shutdown 10 --no-access-log --log-level warning
```

This example assumes the ingress connects from local IPv4 loopback. For a different
topology use only the verified immediate ingress addresses. The service manager must
set an absolute executable and checkout working directory, the revision and trusted
proxy environment, and supervise exactly this process. Do not use `python -m
relay.server`, reload mode, multiple workers, a globally installed uvicorn, or an
unrecorded source directory. Keep private TLS keys outside the repository/image.

## TLS / reverse proxy

Forward `/core/` **without stripping that prefix**, including HTTP/1.1 WebSocket
upgrades and Authorization. Do not rewrite Core to `/v1/trade-rooms` or inject
Ready/role/attempt headers. A same-host nginx example, placed inside an existing
valid TLS server block (certificate/DNS/firewall remain operator-owned):

```nginx
location /core/ {
    proxy_pass http://127.0.0.1:8788;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 60s;
    client_max_body_size 64k;
    access_log off;
}
```

Overwrite, never blindly append/trust user-supplied forwarding headers. If another
trusted ingress precedes nginx, configure its real-IP trust boundary explicitly.
Never set `FORWARDED_ALLOW_IPS=*` or expose the backend to untrusted networks.
Wrong trust configuration groups all users into one rate bucket or permits spoofing.
Set ingress connection/handshake and create/join rate limits appropriate to capacity;
do not impose a short whole-session timeout on WebSockets or game-input waits.
Backend max-message size includes the Core header and generation ID, not just payload.
The HTTP body limit above does not limit upgraded WebSocket frames.

Do not retain bearer headers, Pair codes, response bodies, raw packets, or key material
in proxy/application logs. No packet inspection or payload analytics. The relay is
trusted with plaintext payload inside hop TLS; this is not end-to-end encryption
against its operator. Restrict operational diagnostics to the operator.

## Verification and client handoff

1. Run only the focused deployment/API/WebSocket regressions before cutover:
   `python -m pytest -q tests/test_core_relay_deployment.py tests/test_core_relay_api.py tests/test_core_relay_websocket.py tests/test_core_end_to_end.py`.
   These are local software tests and do not touch the public service or hardware.
2. Verify the staged container/native process and **public** `/core/health` both return
   `status=ok`, `service=switchtrade-core-relay`, `contract_version=switchtrade-pair.v1`,
   and `source_revision` equal to the selected SHA (not `unknown`). Check negative
   legacy routes and WebSocket upgrade/Authorization forwarding. A health 200 alone
   does not prove a two-client data path or a Pokémon trade.
3. Record TLS validation, effective trusted proxy identity, service configuration,
   SHA/image digest, health output, and staged authenticated two-client forwarding
   evidence without credentials. Do not use `python -m relay.smoke`: that targets Room.
4. Only the deployment operator switches the production ingress and retires the exact
   old service. Provide the verified **base URL**, without `/core` appended, to users.

Both Windows sessions then use the same URL:

```powershell
$env:SWITCHTRADE_CORE_RELAY = 'https://relay.example.org'
Invoke-RestMethod "$env:SWITCHTRADE_CORE_RELAY/core/health"
# Physical Switch Host (radio prerequisites still apply):
.\dev.ps1 run host
# VM Guest, after user manually starts the supported RetroArch/gpSP game:
.\dev.ps1 run join <six-digit-code> --emulator gpsp
```

RetroArch connects locally to `127.0.0.1:55435`, never to the Internet relay.
See the [VMware runbook](../docs/core-simplification/GPSP_VMWARE_RUNBOOK.md) for
game/menu timing and two-Generation physical checks. Deployment is not physical PASS.

## Rollback and stop

Stop only the identified Core service/process after coordinating active sessions.
Preserve the first failure, bounded redacted logs and image/source identity; verify
its listener/process is absent before reusing the port. Restore the previously
recorded ingress and image/service configuration if needed, without deleting old
volumes. Core rollback requires new Pairs. Returning to the Room service does **not**
restore compatibility for Core clients; tell users explicitly and stop the test.
The [historical Room guide](DEPLOYMENT_LEGACY.md) is archival, not this deployment.
