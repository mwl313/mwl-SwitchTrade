# PC B handoff — M7 safe distributed qualification

Use only GitHub prerelease `v0.2.10-beta.1` and the exact tag checkout. The complete commands and stop
conditions are in `docs/HANDOFF-M7-TWO-PC-DISTRIBUTED-20260830.md`.

PC B must:

1. Install the new release and select its own RTL8192EU adapter once.
2. Check out `v0.2.10-beta.1` detached and prove the installed release ID equals
   `beta-<first 12 characters of git rev-parse HEAD>`.
3. Confirm the adapter is Windows-owned and the PC B state root is fresh.
4. Run `join` once with PC A's fresh `distributed-invitation.v2` value.
5. Stop when `coordination_paired` appears. Report that checkpoint to PC A; do not press Enter until
   PC A reports the same test ID and checkpoint.
6. After both sides confirm, press Enter to start P0. Operate Switch B only at the later role-specific
   prompt.
7. Report `D11_VERIFIED` and a clean residue check before PC A finalizes the room.

If anything fails, preserve the exact state root and run `recover`. Never reuse the invitation, delete
recovery state, unregister WSL, or use the retired GUI session path to force progress.
