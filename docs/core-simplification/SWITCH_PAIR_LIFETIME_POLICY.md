# Core Pair and Generation lifetime policy

This records software behavior; it is not a physical qualification result.

| Event | Policy |
| --- | --- |
| Unconsumed invite | Six ASCII digits, including leading zeros; ten-minute admission TTL. At expiry Host checks authenticated Pair status once. If not joined, pending local work is canceled and cleaned with `S_PAIR_CODE_EXPIRED`. |
| Consumed invite | Another join returns `PAIR_CODE_CONSUMED` (HTTP 409). Later invite expiry does not terminate the established Pair. Reusing the numeric code for another Pair never transfers old credential ownership. |
| Reconnect lease | The original one-hour timestamp is a new-stream admission deadline, not a healthy ACTIVE-stream TTL. Existing authenticated streams continue; connected records survive store sweep. Expired credentials cannot open a new stream. |
| WAITING without a ready peer | Expired reconnect lease terminates unrecoverable waiting. A consumed invite may outlive its code TTL while the guest socket is still arriving, within this lease. |
| OPENING / NEGOTIATING / ACTIVE | No application-idle deadline. A healthy established stream survives reconnect-lease expiry. Local end, cancellation and actual transport loss remain observable. Loss after the lease ends cannot readmit the expired credential. |
| Actual socket loss | Relay retires both captured old streams, waking silent pre-active waits without forging a peer envelope/sequence. Pending old frames are cleared. ACTIVE may reconnect within the lease after verified cleanup; pre-active operations may fail cleanly. |
| Peer epoch resync | WireState performs the bounded two-source resync. Supervisor retires the stale local generation, but does not reconnect the still-live socket just because its peer rotated an epoch. |
| Native local room end | The Switch endpoint translates Disconnect/Leave events into generic local completion. Core sends/drains generation close and cleans before same-Pair admission. |
| Ctrl+C | Stop the local generation, drain close and authenticated peer-close notification, close the owned socket. No other Pair, interface, or process is targeted. Failed cleanup remains fail-closed. |

Both PCs must select the same reachable relay base URL. CLI consistently maps
`http/ws` to HTTP API + WebSocket and `https/wss` to HTTPS API + secure WebSocket.
Embedded URL credentials, query parameters, fragments and malformed ports are
rejected. Loopback is for one-machine software tests, not two-PC rendezvous.

The existing relay stale-pending raw-envelope regression was strengthened: loss
of an established peer closes the old surviving stream before stale DATA can
accumulate. A fresh connection carries only fresh frames. The independent
two-WireClient dropped-sequence/epoch resync regressions remain mandatory.
