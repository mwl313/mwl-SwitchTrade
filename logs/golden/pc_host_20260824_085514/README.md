# PC-host discovery/join gate — 2026-08-24

- RTL8192EU hosted `CODEX` on CH6 with LDN protocol 3, app version 88.
- RTL8188EU independently captured the session.
- The real Switch displayed the room and joined five times.
- Each attempt timed out after about eight seconds with “the other trainer appears unavailable.”
- LDN discovery/authentication passed; no Pia UDP datagram was sent in either direction.
- Root cause: PC host still runs the joiner/right-seat Pia state machine and never initiates Net 0x11.
- Full report: `docs/26-pc-host-discovery-join-gate-20260824.md`
