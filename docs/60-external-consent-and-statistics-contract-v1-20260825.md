# External consent and statistics contract v1 — 2026-08-25

> Status: frozen product contract; legal and security approval is still required before collection.
> Contract version: `privacy-statistics.v1`.
> Scope: optional committed-trade statistics for the private beta.

The Windows client intentionally has no Privacy tab or analytics switch. Enrollment, consent text,
revocation, export, and deletion are handled by an external operator workflow. This does not make
analytics implicit: collection is disabled unless the server can verify an active, versioned grant.

## 1. Product rules

1. Trading and local party display work without analytics.
2. Default state is `disabled`; missing, expired, revoked, or unreachable consent state also means
   disabled.
3. Beta consent is explicit, purpose-specific, versioned, and independently revocable.
4. The WPF client never receives analytics bearer credentials and never offers a misleading local
   consent control.
5. The relay never decodes RFU traffic and never receives party snapshots.
6. Only a validated `trade.committed` projection can reach statistics ingestion.
7. The client never sends an IP address or claimed location. The service uses the connection source IP.
8. No collection starts until the Gate 8 legal/privacy and security reviews approve the deployed policy.

## 2. Consent grant

A grant is stored server-side and cached only as a non-secret decision in the local runtime.

```json
{
  "contract_version": "privacy-statistics.v1",
  "grant_id": "cg_01...",
  "subject_id": "beta_01...",
  "policy_version": "2026-08-25.1",
  "scopes": ["committed_trade_statistics"],
  "status": "active",
  "granted_at": "2026-08-25T10:00:00Z",
  "expires_at": "2026-11-25T10:00:00Z"
}
```

Both room members must have an active grant for a two-party record to be ingested. A revocation takes
effect for new commits immediately after server receipt and queues eligible historical deletion under
the policy below. Consent audit records contain the policy decision, not Pokémon or RFU data.

## 3. Permitted committed-trade record

One accepted record may contain:

- `commit_id`, server room/session identifiers, UTC commit timestamp, product/protocol versions, and
  outcome (`committed` or `committed_with_teardown_error`);
- pseudonymous member and trainer identifiers scoped to the service;
- the two exchanged, checksum-valid Pokémon records: species, nickname, level, nature, held item,
  moves, friendship, language, original trainer name/IDs, personality value, ability, gender, shiny
  result, IVs, EVs, contest stats, ribbons, markings, and provenance for each available field;
- coarse network geography derived by the server: country and first-level administrative region;
- operational quality facts such as adapter profile, connection duration, reconnect count, and redacted
  error codes.

Unavailable values stay unavailable. The service must not infer or manufacture values.

## 4. Prohibited data

The statistics path must not receive:

- full six-Pokémon party snapshots or non-traded Pokémon;
- raw RFU frames, decrypted payloads, session keys, packet captures, memory dumps, or arbitrary logs;
- GPS, street address, precise coordinates, city-level location, Wi-Fi SSIDs/BSSIDs, or nearby devices;
- a client-supplied IP address;
- account passwords, Nintendo credentials, prod keys, save files, or unrelated system inventory.

## 5. IP and location handling

The edge may retain the source IP in a restricted security dataset for abuse prevention. Before a record
enters analytics, the service derives:

- a keyed, rotating pseudonymous network identifier; and
- country plus first-level administrative region.

The raw IP is not copied into the analytics record. Network identifiers must not be stable across
unrelated products and must rotate at least annually. Location enrichment must use the server-observed
IP and a documented database version.

## 6. Retention baseline

| Dataset | Retention | Access |
| --- | --- | --- |
| Raw source IP security record | 7 days | Restricted security operators only |
| Detailed committed-trade record | 180 days | Authorized product/statistics operators |
| Consent and revocation audit | Active grant plus 365 days | Privacy/security operators |
| De-identified aggregate statistics | 24 months | Authorized product analysts |
| Local party snapshots and decoder buffers | Current attempt only | Local runtime process |

Security incidents may require a documented legal hold. A hold must be scoped, audited, and must not be
used as normal retention.

## 7. Export, deletion, and revocation

- The external workflow authenticates a participant before export or deletion.
- Requests are completed within 30 days unless applicable law requires a shorter period.
- Deletion removes identifiable/pseudonymous detailed records and invalidates linkable lookup keys;
  already de-identified aggregates that cannot reasonably be relinked may remain if the approved policy
  says so.
- Every export, deletion, denial, and revocation action is audited without copying the subject data into
  the audit entry.

## 8. Ingestion boundary

The local runtime submits an idempotent commit projection over authenticated TLS. The service:

1. derives the source IP from the accepted connection;
2. verifies both consent grants and exact scope at ingestion time;
3. rejects unknown contract/policy versions;
4. applies a unique constraint on `commit_id`;
5. validates the record against `party-commit.v1` provenance and field allowlist;
6. returns accepted, duplicate, disabled, or rejected without changing the local trade result.

Retries are bounded and asynchronous. Offline statistics may be queued only in an encrypted local store
with the same retention deadline; otherwise the projection is discarded. A statistics outage is never
a trading outage.

## 9. Security and logging

- encrypt data in transit and at rest;
- separate operational, security, and analytics access roles;
- store grants and service credentials outside WPF and redact them from support bundles;
- log decision codes, contract versions, `commit_id`, and delivery state, not decoded Pokémon fields;
- rate-limit ingestion and audit administrative access;
- document key rotation, breach response, backup retention, and deletion propagation before beta.

## 10. UI contract

The desktop UI may show only a neutral externally managed enrollment status when product requirements
later call for it. For the first product demo it shows no privacy controls, no consent prompt, and no
claim that statistics were uploaded. Trade success is based solely on the local commit classifier.

This document is an engineering baseline, not legal approval or legal advice. Gate 8 remains open until
the actual policy, notices, operator workflow, retention implementation, and security controls are
reviewed for the deployment jurisdictions.
