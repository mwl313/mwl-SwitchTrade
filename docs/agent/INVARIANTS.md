# Global invariants

These rules apply to every task. They are intentionally short; historical evidence remains in the
immutable incident archive.

- Preserve the first functional failure; cleanup failures are secondary evidence.
- `unknown` is not `absent`, ready, clean, or successful.
- One run owns one endpoint and one hardware lease.
- Polling and status reads never launch, revive, retry, or recover work.
- Do not start another generation until cleanup is verified.
- Bind source, runtime, process, device, and release claims to exact identities.
- Never commit credentials, MACs, captures, Pokémon data, or private paths.
- Unit tests prove only their modeled scope.
- Never bypass source, identity, hardware, protocol, privacy, cleanup, or physical gates.
