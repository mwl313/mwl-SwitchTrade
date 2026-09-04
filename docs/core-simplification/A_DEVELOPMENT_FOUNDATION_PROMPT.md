# Phase A Implementation Prompt
## Development Foundation

You are implementing **Phase A only** of the SwitchTrade Core Simplification Program.

This prompt is intended for Terra or Luna. Do not continue into Phase B or C.

---

## 0. Working rules

1. Work in repository `mwl313/mwl-SwitchTrade`.
2. Record the current branch, `git rev-parse HEAD`, and `git status --short`.
3. Use or create `core-simplification` only from a clean current `main`.
4. Do not push directly to `main`.
5. Make separate commits for A1, A2, and A3.
6. Do not perform unrelated cleanup or refactoring.
7. Preserve the first test failure and report it accurately.
8. Do not claim physical, installer, USB, RF, or production acceptance from unit tests.

### One-time context migration exception

The current root `AGENTS.md` requires reading the complete legacy
`docs/MISTAKES_TO_AVOID.md`. This task exists specifically to remove that unbounded policy.

For **A1 only**:

- treat the legacy incident body as opaque historical bytes;
- do not semantically load or rewrite the complete body;
- use filesystem operations and a deterministic script to move it and extract headings;
- read only enough of the beginning to identify its format and preserve its authority statement;
- do not modify runtime, installer, relay, protocol, or product code.

After A1, follow the newly created bounded agent-context policy.

---

# 1. Goal

Deliver two independent improvements:

1. Replace mandatory full-history reading with bounded, path-routed context while preserving all
   historical evidence.
2. Add source-only hot deployment into the installed SwitchTrade WSL runtime so normal source
   changes do not require the installer.

---

# 2. Non-goals

Do not:

- remove Room, Lobby, Ready, WPF, authority, or existing production code;
- implement Pair Relay or CoreSupervisor;
- modify DirectAStage, DirectBStage, TunnelSim, or RFU behavior;
- make WSL portable;
- import or unregister a WSL distribution;
- modify the replacement Provisioner lifecycle;
- change `.wslconfig`, kernel, modules, drivers, firmware, or usbipd;
- install dependencies automatically;
- copy `config/prod.keys` into the overlay;
- alter `/opt/switchtrade`;
- modify release/package behavior;
- rewrite or summarize the legacy archive.

---

# 3. Preferred output

```text
AGENTS.md
docs/MISTAKES_TO_AVOID.md
docs/agent/INVARIANTS.md
docs/agent/CONTEXT_MAP.md
docs/incidents/INDEX.md
docs/incidents/ARCHIVE_MANIFEST.json
docs/incidents/archive/MISTAKES_TO_AVOID-legacy-20260901.md
tools/build_incident_index.py
tests/test_agent_context_policy.py

dev.ps1
scripts/dev/DevOverlay.psm1
scripts/dev/install-overlay.sh
scripts/dev/dev-source-allowlist.txt
scripts/dev/README.md
tests/test_dev_hot_deploy_contract.py
```

Narrow path adjustments are allowed, but do not merge these responsibilities into large existing files.

---

# 4. Work packet A1 — Agent context migration

## Allowed files

- `AGENTS.md`
- `docs/MISTAKES_TO_AVOID.md`
- `docs/agent/**`
- `docs/incidents/**`
- `tools/build_incident_index.py`
- `tests/test_agent_context_policy.py`

## Forbidden files

Everything else.

## Required implementation

1. Calculate the original SHA-256 and byte size of `docs/MISTAKES_TO_AVOID.md`.
2. Move it byte-for-byte to
   `docs/incidents/archive/MISTAKES_TO_AVOID-legacy-20260901.md`.
3. Create `docs/incidents/ARCHIVE_MANIFEST.json` containing schema, original path, archive path,
   byte size, and SHA-256.
4. Replace the old path with a short routing stub stating:
   - the archive is historical evidence;
   - it is not mandatory default context;
   - agents should search `docs/incidents/INDEX.md`;
   - only matching incidents should be opened.
5. Implement `tools/build_incident_index.py` with the Python standard library only.
   Mechanically extract incident headings/IDs and generate deterministic `INDEX.md`.
6. Replace root `AGENTS.md` with bounded rules:
   - exact branch/base/status;
   - nearest applicable instructions;
   - one work packet / one conceptual boundary;
   - task-relevant docs only;
   - never load the full archive by default;
   - incident lookup triggers;
   - global invariants;
   - tests and handoff.
7. Add `docs/agent/INVARIANTS.md` and `CONTEXT_MAP.md`.
8. Preserve at minimum:
   - first functional failure is primary;
   - cleanup failures are secondary;
   - unknown is not absent;
   - one run owns one endpoint and hardware lease;
   - polling/status reads do not launch or revive work;
   - cleanup is verified before another generation;
   - credentials, MACs, captures, Pokémon data, and private paths are not committed;
   - unit tests prove only modeled scope;
   - safety gates are not bypassed.
9. Add tests that fail if:
   - archive hash differs;
   - generated index is stale;
   - root AGENTS exceeds 120 lines or 8 KiB;
   - active instructions require a full archive read;
   - active policy makes the archive mandatory default context.

## Acceptance

- Archive bytes match exactly.
- Runtime source is unchanged.
- Index is deterministic.
- Active policy is bounded.
- Tests pass.

## Commit

```text
docs: replace mandatory full incident reads with bounded context
```

Stop and report A1 before A2.

---

# 5. Work packet A2 — Development source hot-deploy

## Allowed files

- `dev.ps1`
- `scripts/dev/**`
- `tests/test_dev_hot_deploy_contract.py`
- minimal documentation links exposing the command

## Forbidden files

- `installer/replacement/SwitchTrade.Provisioner/**`
- `installer/replacement/wix/**`
- `apps/desktop/**`
- `relay/**`
- `switchtrade/connection/**`
- `bridge/frlgsim/**`
- production package manifests
- dependency lock files
- `config/prod.keys`

## Command surface

```powershell
.\dev.ps1 doctor
.\dev.ps1 sync
.\dev.ps1 run -- <arguments>
.\dev.ps1 test -- <pytest arguments>
.\dev.ps1 clean
```

A slightly different PowerShell argument syntax is allowed only if it stays simple and documented.

## Runtime discovery

Read:

```text
%LOCALAPPDATA%\SwitchTrade\state\active-runtime.json
```

Require:

- schema `1`;
- safe non-empty `active_runtime`;
- named distro exists;
- ownership marker identifies SwitchTrade;
- `/opt/switchtrade/bridge/.venv/bin/python` is executable.

Do not guess a distro name.

## Compatibility gate

Compare local and installed hashes for:

```text
requirements.txt
bridge/requirements.txt
```

On mismatch, fail with `DEV_DEPENDENCY_MISMATCH`.
Do not run pip, apt, Repair, Install, or Update.

## Source bundle

Use an explicit allowlist. Exclude:

- `.git`;
- venvs/caches;
- artifacts/logs/captures/support bundles/archives;
- `config/prod.keys`;
- credentials/tokens;
- kernel/installer payloads.

Include untracked files only beneath an allowed source path and not ignored/forbidden.

Create a deterministic manifest from sorted relative paths and SHA-256 hashes.
Derive the content ID from that manifest so dirty changes produce a new identity.

## WSL overlay

Install to:

```text
/opt/switchtrade-dev/releases/<content-id>
```

Maintain:

```text
/opt/switchtrade-dev/current
```

Requirements:

- staging extract;
- hash verification inside WSL;
- atomic release commit;
- atomic `current` switch;
- no overwrite;
- concurrent sync lock;
- retain current and previous release;
- interrupted staging cannot alter current;
- clean only `/opt/switchtrade-dev`.

## Process invocation

Every WSL call specifies exact distribution, explicit user, Linux cwd, executable, and safe argv.

Use:

```text
/opt/switchtrade/bridge/.venv/bin/python
```

Source:

```text
/opt/switchtrade-dev/current
```

Set:

```text
PYTHONNOUSERSITE=1
PYTHONPATH=/opt/switchtrade-dev/current
SWITCHTRADE_SOURCE_ROOT=/opt/switchtrade-dev/current
SWITCHTRADE_INSTALLED_ROOT=/opt/switchtrade
```

Never rely on translated Windows cwd.

## Stable errors

Implement clear equivalents of:

- `DEV_ACTIVE_RUNTIME_MISSING`
- `DEV_ACTIVE_RUNTIME_INVALID`
- `DEV_WSL_RUNTIME_NOT_REGISTERED`
- `DEV_RUNTIME_OWNERSHIP_INVALID`
- `DEV_PYTHON_MISSING`
- `DEV_DEPENDENCY_MISMATCH`
- `DEV_SOURCE_ALLOWLIST_EMPTY`
- `DEV_SOURCE_FORBIDDEN`
- `DEV_DEPLOY_BUSY`
- `DEV_ARCHIVE_FAILED`
- `DEV_EXTRACT_FAILED`
- `DEV_MANIFEST_MISMATCH`
- `DEV_COMMIT_FAILED`
- `DEV_RUN_FAILED`
- `DEV_CLEAN_REFUSED`

## Tests

Add deterministic tests for:

- active-runtime parsing;
- safe runtime name;
- allowlist/denylist;
- forbidden secrets;
- deterministic content ID;
- dirty-file identity;
- dependency mismatch;
- exact WSL cwd/executable construction;
- no production write/delete;
- cleanup containment;
- PowerShell parse;
- shell syntax.

Default tests must not require live WSL.

## Commit

```text
dev: add source-only hot deploy for installed WSL runtime
```

Stop and report A2 before A3.

---

# 6. Work packet A3 — Verification and documentation

## Required checks

1. Run policy tests.
2. Run hot-deploy contract tests.
3. Run relevant existing software tests.
4. Parse every changed PowerShell/shell file.
5. If an installed runtime is available:
   - doctor;
   - sync;
   - import an overlay-only marker;
   - change a harmless marker and sync again;
   - prove new content ID;
   - sample-hash production files before/after;
   - clean;
   - prove `/opt/switchtrade` unchanged;
   - prove no installer invoked.
6. Without live WSL, report the live smoke as **not executed**, not passed.

## Documentation

Document commands, paths, mismatch behavior, installer-required changes, clean behavior, interrupted sync
recovery, and security exclusions.

## Commit

```text
test: qualify bounded agent context and WSL dev overlay
```

---

# 7. Required final response

```markdown
## Baseline
- Branch:
- Base commit:
- Initial working tree:

## Commits
- A1:
- A2:
- A3:

## Changed files
...

## Design decisions
...

## Tests executed
| Command | Result | Scope |
...

## Live WSL smoke
- Executed:
- Runtime:
- Result:
- Production path unchanged evidence:

## Stable errors added
...

## Deviations
...

## Remaining risks
...

## Phase A verdict
PASS / FAIL
```

Do not begin Phase B.
