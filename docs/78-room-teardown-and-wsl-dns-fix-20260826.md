# Room teardown and WSL DNS fix — 2026-08-26

## Reported symptom

After joining a room created by another client, pressing Leave Trade Room produced the in-room notice
`Connection needs attention — Online rooms are temporarily unavailable.` The owner/creator inverse and
End connection paths also required qualification.

The room being created by the owner's Mac agent was valid and was not the cause.

## Root causes

Three independent conditions combined:

1. The relay DNS record had just been restored. WSL's host/Tailscale DNS proxy answered a combined
   A/AAAA lookup with only Cloudflare IPv6 addresses, but this WSL instance had no IPv6 default route.
   Explicit IPv4 resolution and connection succeeded. Glibc `single-request-reopen` returned both
   families and restored relay access.
2. The remote member leave had already committed before the connection failed. The server correctly
   returned the public room to occupancy 1/2, but this PC did not receive the success response and kept
   expired local member/reconnect credentials. Retrying was misreported as relay unavailability.
3. Presence heartbeats can advance the authoritative room version between the client's snapshot and
   termination request. Production returned `409 room version conflict` for both member leave and owner
   close even though these terminal commands remain safe after a presence-only version change.

End connection itself already stops the local RFU endpoint first and treats failed authority sync as a
warning. A regression test now locks this behavior so a relay outage cannot keep a local radio session
running.

## Corrections in `71d936c`

- The POSIX relay client appends `single-request-reopen` to `RES_OPTIONS`, preserving any existing
  resolver options. This avoids the WSL/Tailscale parallel A/AAAA loss observed on the development PC.
- Member leave and owner close are locally idempotent. If the remote membership/room is already gone,
  the client clears its expired local authority state and completes without a false outage notice.
- The relay authority permits stale expected versions for authenticated `leave` and `close` only.
  Authorization, owner/member rules, active-attempt teardown rules, and the existing version policies
  for all other actions remain unchanged.

## Verification

- Targeted tests failed before the fixes and pass after them.
- Product test suite: 90 passed.
- Native WPF Release build: 0 warnings, 0 errors.
- Preserved real member state after the failed UI leave: retry returned HTTP 200 and local state cleared.
- Installed private owner room creation and close: HTTP 200; final room version 2; local room absent.
- End connection with simulated relay DNS failure: HTTP 200 `stopped`.
- Public Rooms through installed control: five consecutive HTTP 200 responses.
- Actual package Update to `beta-71d936c`: PASS; installed self-test and relay readiness PASS.
- Production stale-version probe: member leave 409 and owner close 409; cleanup close 200. This proves
  the hosting agent must deploy relay commit `71d936c` before the server-side race fix is live.

## Candidate

- Package: `SwitchTrade-unsigned-private-beta-71d936c.zip`
- SHA-256: `1656effd19ac4c7f6577c5b272805566b43fe0fd715a81f1ebc4adf26fb028e8`
- Signing: explicitly unsigned private beta

The installed client on this PC already contains the fix. The owner/member termination matrix is
internally complete; final remote qualification requires deployment of the matching relay commit.
