# Active incident ledger

This file receives detailed incidents discovered after the 2026-09-03 documentation compaction.
Earlier incidents are preserved unchanged in
[`MISTAKES_TO_AVOID_HISTORY-20260903.md`](../MISTAKES_TO_AVOID_HISTORY-20260903.md).

Before assigning an ID, run `python tools/validate_mistakes_docs.py` and inspect the maximum number
for the intended category in [`INCIDENT_INDEX.md`](INCIDENT_INDEX.md). Append entries; do not reorder
or renumber history.

Each incident must use this heading form:

```text
### MTA-AREA-NNN — Short factual title
```

Each entry records the observed symptom, safe source/run/release identity, last passed gate, cause
certainty, disproven alternatives, recovery and residue result, correction status, and one concrete
automated/installed/physical prevention gate. Update a domain guide only when the entry changes a
reusable rule.

Rotate this file into a dated archive before it exceeds 1,000 lines, then update the validator's
archive list and regenerate the index.

### MTA-OPS-185 — Do not review a compressed ledger through its full deletion diff

- **Observed failure:** A read-only staged-diff review included the compact replacement for the
  former 5,000-line prevention ledger. Git emitted the entire historical deletion, the aggregate
  tool output was truncated, and that output could not serve as completeness evidence. The branch,
  staged files, tests, product, installer, VM, WSL, and external state were unchanged.
- **Cause certainty:** certain. A full textual diff is the wrong review boundary for a deliberately
  archived large document even when the archive itself is excluded from the command.
- **Disproven alternatives:** The documentation validator had already proved all 339 incident IDs,
  required files, local links, index identity, and the 157-line core. This was output selection, not
  content loss or a failed archive move.
- **Recovery and residue:** Discard the truncated output, preserve the staged state, and inspect
  status/statistics plus each new compact file in bounded reads. No runtime cleanup is required.
- **Correction status:** process correction recorded before continuing the pre-commit review.
- **Mandatory prevention gate:** For a large-document compaction, review rename/archive identity with
  hashes and line/incident counts, then review only the new compact files individually. Never request
  the complete deletion diff of the archived source.

### MTA-OPS-186 — Keep independent index checks in independent invocations

- **Observed failure:** A read-only verification placed two independent fixed-string `rg` checks in
  one PowerShell invocation on separate lines. Both checks returned valid bounded output and changed
  no source, test, product, installer, VM, WSL, or external state, but the command shape violated the
  newly consolidated one-operation evidence rule.
- **Cause certainty:** certain. The checks were combined for convenience after the applicable rule
  had already been read and rewritten.
- **Disproven alternatives:** No shell separator or mutating command was involved, and neither result
  was masked; this is a process-rule violation rather than corrupt evidence.
- **Recovery and residue:** Preserve both factual results, record this incident, and issue every
  remaining pre-commit check as one independent command. No runtime cleanup is required.
- **Correction status:** process correction recorded before final validation.
- **Mandatory prevention gate:** One evidence question per shell invocation, including multiple
  read-only searches against the same file. Use a single deliberately shared search expression only
  when one combined result is itself the evidence contract.

### MTA-OPS-187 — Place every ripgrep option before the end-of-options marker

- **Observed failure:** A read-only desktop-code search placed two `-g` file filters after `--`.
  Ripgrep treated the filters as paths, rejected them on Windows, and returned only partial results.
  No source, product, installer, VM, WSL, process, or external state changed.
- **Cause certainty:** certain. The command contradicted the already-read Windows ripgrep rule; every
  option must precede `--`, followed only by the pattern and concrete directory operands.
- **Disproven alternatives:** The reported file errors and partial matches came from argument order,
  not missing source files or an application defect.
- **Recovery and residue:** Reject the partial output, record this incident, then repeat the search
  with both `-g` filters before `--`. No runtime cleanup is required.
- **Correction status:** process correction recorded before resuming the status audit.
- **Mandatory prevention gate:** Visually enforce `rg [options and -g filters] -- pattern directories`
  before every Windows ripgrep call; no token beginning with `-` may follow `--`.

### MTA-OPS-188 — Discover exact installer source paths before reading them

- **Observed failure:** A read-only inspection guessed that the EmulatorVM bundle source was named
  `Bundle.EmulatorVM.wxs`; that path does not exist, so no source evidence was obtained. No source,
  product, installer, VM, WSL, process, or external state changed.
- **Cause certainty:** certain. A conventional sibling filename was inferred instead of being
  discovered from the repository.
- **Disproven alternatives:** The failure is not evidence that the EmulatorVM bundle or build is
  absent; it proves only that the guessed source path was wrong.
- **Recovery and residue:** Reject the failed read, record this incident, enumerate the bounded
  installer tree with `rg --files`, and read only an exact returned path. No cleanup is required.
- **Correction status:** process correction recorded before resuming the status audit.
- **Mandatory prevention gate:** Before every direct read of an unobserved sibling artifact, resolve
  its exact path with `rg --files`; never derive it from a neighboring filename.

### MTA-OPS-189 — Do not assume conventional top-level source directories

- **Observed failure:** A read-only relay search included guessed top-level `src` and `deploy`
  directories that do not exist in this workspace. Ripgrep rejected those operands and returned only
  partial test matches. No source, product, installer, VM, WSL, process, or external state changed.
- **Cause certainty:** certain. Repository layout was inferred instead of discovered.
- **Disproven alternatives:** The partial result says nothing about relay capability implementation or
  deployment; the invalid directory operands made that evidence incomplete.
- **Recovery and residue:** Reject the partial output and stop the out-of-scope relay audit after the
  user clarified that only the preceding installer discussion is requested. No cleanup is required.
- **Correction status:** process correction recorded before the operator report.
- **Mandatory prevention gate:** Resolve repository search roots from `rg --files` or already-observed
  paths before a multi-directory search; never add conventional top-level names speculatively.

### MTA-OPS-190 — Emit scalar artifact facts instead of width-dependent tables

- **Observed failure:** A read-only MSI size query formatted the full path and length as a PowerShell
  table. Console width collapsed the length column, so the successful command did not provide the
  requested exact byte count. No source, product, installer, VM, WSL, process, or external state
  changed.
- **Cause certainty:** certain. The file query succeeded; presentation formatting made the evidence
  incomplete.
- **Disproven alternatives:** The clipped display is not evidence of a missing, truncated, or invalid
  MSI artifact.
- **Recovery and residue:** Reject the formatted result, record this incident, and repeat the query as
  one invariant-culture scalar value. No cleanup is required.
- **Correction status:** process correction recorded before continuing kit design.
- **Mandatory prevention gate:** Exact sizes, hashes, counts, IDs, and exit codes are emitted as plain
  scalar text or compact JSON, never as width-dependent tables.

### MTA-OPS-191 — Launch the relay through one import identity

- **Observed failure:** The first physical-test relay start used `python -m relay.server`. The module
  acquired the unique SQLite writer lock as `__main__`, then `uvicorn.run("relay.server:app")`
  imported the same module a second time and failed with `AlreadyRunningError`. The script preserved
  the bounded stderr and run identity, terminated its exact child PID, and marked the run
  `failed_cleaned`.
- **Cause certainty:** certain from the traceback and absent child-process residue. The unique
  authority database path rules out a competing prior relay; the duplicate import happened inside
  the one launched process.
- **Disproven alternatives:** Port 8788 was free before launch, the selected VMware-host address was
  local, and the heterogeneous capability check never ran because application import failed.
- **Recovery and residue:** PID 20996 is absent; the failed run state and logs remain under its private
  evidence root. No room, credential, listener, VM, WSL, radio, or product process was created.
- **Correction status:** corrected launcher passed a real start, capability, graceful-stop cycle.
- **Mandatory prevention gate:** Process launchers must invoke `python -m uvicorn relay.server:app`
  with one worker and explicit host/port, and their self-test must freeze that single-import argv.

### MTA-OPS-192 — Persist process start identity as ticks

- **Observed failure:** The corrected test relay started and advertised the required capability, but
  `stop-relay` rejected its own PID as `PROCESS_IDENTITY_CHANGED`. The saved process hash still
  matched; the saved ISO start string had been coerced to a locale-formatted value with subsecond
  precision removed, so exact string equality failed. The owned relay remains live while recovery
  identity is established.
- **Cause certainty:** certain from the saved/current start values and identical executable hashes.
  The live PID also has the exact uvicorn module, bind address, port, and single-worker argv recorded
  for this run.
- **Disproven alternatives:** PID reuse, executable replacement, an unrelated relay, and wrong launch
  arguments are excluded by the live process/hash/argv observations.
- **Recovery and residue:** Use the exact relay URL's committed shutdown endpoint only after the PID,
  executable hash, uvicorn entry, host, port, and worker count match; then prove the PID and listener
  are absent. Preserve the run database and logs.
- **Correction status:** committed shutdown removed the exact process/listener and the tick-based
  identity passed the subsequent real cycle.
- **Mandatory prevention gate:** Persist and compare `StartTime.ToUniversalTime().Ticks` as an integer
  for every owned process; self-test the state round trip and never rely on culture-sensitive date
  serialization for process identity.

### MTA-OPS-193 — Rebuild deserialized state before adding terminal fields

- **Observed failure:** The tick-corrected relay passed start and accepted its authenticated shutdown,
  but `stop-relay` then tried to assign a new `stopped_utc` property to the fixed `PSCustomObject`
  returned by `ConvertFrom-Json`. PowerShell rejected the property addition after the relay had
  already exited.
- **Cause certainty:** certain from the property-assignment exception. PID 5856 and its listener are
  both absent, proving functional cleanup completed before evidence finalization failed.
- **Disproven alternatives:** The relay did not hang, require force, retain the listener, or fail its
  shutdown endpoint; only the terminal state write failed.
- **Recovery and residue:** Preserve the pre-terminal state and stopped-process observations. Rebuild
  a new ordered state dictionary containing the old fields plus terminal fields, then persist it; do
  not rerun shutdown against the absent PID.
- **Correction status:** terminal state rebuilding passed self-test and the subsequent real cycle.
- **Mandatory prevention gate:** Any JSON-deserialized state update that adds fields must construct a
  new dictionary (or use explicit `Add-Member`) and pass a self-test for both normal and forced-stop
  terminal serialization.

### MTA-OPS-194 — Bind every relay run to the packaged release ID

- **Observed failure:** A relay verification command omitted the required `ExpectedReleaseId`
  parameter. The controller rejected the request with `EXPECTED_RELEASE_REQUIRED` before creating a
  process, listener, database, room, credential, VM, WSL, radio, or product state.
- **Cause certainty:** certain. The command line lacked the parameter and the controller's first
  release-identity guard produced the exact failure.
- **Disproven alternatives:** The failure does not indicate a relay, network, package, or capability
  defect because execution stopped before any of those checks or mutations.
- **Recovery and residue:** Preserve the rejected command as the first failure and verify that no
  active relay state was created. Read the release ID from the already-verified package manifest,
  then retry once with that exact value.
- **Correction status:** retry with the manifest release ID passed start and graceful stop.
- **Mandatory prevention gate:** Every relay start command and runbook example must pass the exact
  package `release_id`; never rely on an implicit or remembered development release identity.

### MTA-OPS-195 — Put ripgrep glob options before the search path

- **Observed failure:** A read-only WiX identity search placed `-g` glob options after the directory
  operand. On Windows, ripgrep treated them as paths, emitted operand errors, and returned only a
  partial result. No source, installer, product, process, VM, WSL, radio, or external state changed.
- **Cause certainty:** certain from the command ordering and explicit `-g` path errors.
- **Disproven alternatives:** The partial output is not evidence that the requested WiX definitions
  or project files are absent.
- **Recovery and residue:** Reject the partial search. Use the exact WiX paths it did reveal for a
  bounded direct read rather than repeating a broader search. No cleanup is required.
- **Correction status:** operator-command correction recorded before continuing the upgrade audit.
- **Mandatory prevention gate:** Place all ripgrep flags and `-g` filters before `--`, pattern, and
  path operands; treat any operand error as invalidating the entire search result.

### MTA-OPS-196 — Keep Git mutation and verification in separate shell invocations

- **Observed failure:** The staging command appended `git status` after `git add` in one PowerShell
  invocation. Both operations succeeded and the status named only the intended files, but the call
  violated the repository rule that one shell invocation answer one operation or evidence question.
- **Cause certainty:** certain from the literal command separator and combined output.
- **Disproven alternatives:** No unintended path was staged, no commit was created, and no product,
  installer, process, VM, WSL, radio, or external state changed.
- **Recovery and residue:** Preserve the successful exact-path staging, record the process violation,
  regenerate the incident index, then inspect and commit in separate invocations.
- **Correction status:** process correction recorded before commit.
- **Mandatory prevention gate:** Run each Git mutation and each Git evidence query in its own shell
  invocation; never append a status, diff, or log command to a mutating Git command.

### MTA-OPS-197 — Keep independent documentation searches in separate invocations

- **Observed failure:** One read-only shell invocation joined two independent fixed-string searches
  for separate TODO headings. Both searches succeeded, but the combined call violated the rule that
  independent evidence questions remain separate. No installation, registry, process, VM, WSL,
  radio, source, or external state changed.
- **Cause certainty:** certain from the two commands and separator in the literal invocation.
- **Disproven alternatives:** The returned line numbers are valid; this incident concerns evidence
  isolation rather than missing or incorrect documentation.
- **Recovery and residue:** Preserve the discovered exact line numbers, record the process violation,
  and read each required bounded section in its own invocation. No cleanup is required.
- **Correction status:** process correction recorded before uninstall discovery.
- **Mandatory prevention gate:** Even when commands are read-only, use one shell invocation per
  independently answerable documentation search or range read.

### MTA-OPS-198 — Do not encode multi-scope registry discovery as one inline expression

- **Observed failure:** The first read-only uninstall-registration discovery compressed nested hive,
  registry-view, key, and value loops into one shell line. A mismatched brace caused a parser error,
  so the script did not execute and no registry key, installer, process, product, VM, WSL, radio, or
  external state changed.
- **Cause certainty:** certain from the PowerShell parser's missing Catch/Finally diagnostic and the
  rejected command text.
- **Disproven alternatives:** The failure provides no evidence about how many SwitchTrade entries are
  registered or whether their uninstall engines exist.
- **Recovery and residue:** Reject the command completely. Use a simple bounded registry-provider
  query for each explicitly named uninstall scope and return only non-sensitive identity fields.
- **Correction status:** discovery method corrected before any uninstall mutation.
- **Mandatory prevention gate:** Multi-scope registry discovery must use a reviewed script or simple
  provider pipeline; do not compress nested resource-lifetime logic into an inline shell expression.

### MTA-OPS-199 — Preserve collection shape for a single RunOnce match

- **Observed failure:** `recover-retired-full` found the one expected RunOnce entry but PowerShell
  unrolled the assignment result to a scalar string. Under `Set-StrictMode`, that string exposes no
  `Count` property, so recovery stopped with a type error before launching UAC or the uninstall
  engine.
- **Cause certainty:** certain from the unchanged two registrations/RunOnce entry, zero installer
  process residue, and a read-only reproduction showing runtime type `System.String` with only the
  `Length` property.
- **Disproven alternatives:** No bundle, MSI, product, runtime, registry, VM, WSL, or radio mutation
  began; this was not a permission denial, missing engine, hash mismatch, or uninstall failure.
- **Recovery and residue:** Preserve the registrations and RunOnce entry. Force the pipeline result
  to an array at the assignment boundary, add the exact single-match case to self-test, and only then
  retry the committed identity-bound recovery action.
- **Correction status:** array-boundary correction passed both PowerShell runtimes and the exact
  0.2.20 recovery, removing its registration and RunOnce entry with zero process residue.
- **Mandatory prevention gate:** Any PowerShell value later accessed through `Count` or numeric index
  must be wrapped at its assignment boundary and tested for zero, one, and multiple results under
  `Set-StrictMode`.

### MTA-OPS-200 — Silence is not a registered-bundle uninstall result

- **Observed failure:** The first exact-engine removal attempt for the remaining registered
  `SwitchTrade Setup` 0.2.19 entry returned no terminal JSON or error. A bounded post-check found the
  same bundle ID still registered and zero bundle/MSI processes, so the requested removal did not
  complete.
- **Cause certainty:** investigating. The engine path, registration identity, supported uninstall
  shape, and SHA-256 passed preflight, but the shell produced no process exit evidence to explain the
  unchanged registration.
- **Disproven alternatives:** The entry was not removed asynchronously and no installer process
  remains active. Silence cannot be treated as success or as authorization to delete the key.
- **Recovery and residue:** Preserve the registration and cached engine unchanged. Inspect the
  bundle's own newest bounded log and invocation behavior before choosing another supported lifecycle
  call; do not retry or manually remove registry/cache state.
- **Correction status:** the silent ad-hoc invocation remains unexplained and rejected as evidence;
  the committed exact-ID recovery action removed 0.2.19 and final residue checks passed.
- **Mandatory prevention gate:** A registered-bundle removal must emit an explicit owned-process exit
  result and then prove registration/process residue; blank output is `unknown` and blocks retry.

### MTA-OPS-201 — Report the actual custom artifact output directory

- **Observed failure:** The corrected physical-test kit built successfully into the explicit `r2`
  directory, but its terminal JSON reported the hard-coded default directory instead. The original
  kit was not overwritten and no product, installer registration, process, VM, WSL, or radio state
  changed.
- **Cause certainty:** certain from the builder source's literal default output string and the
  separately preflighted custom target.
- **Disproven alternatives:** This is not evidence that files were copied to the default directory;
  the defect is confined to the completion message and the actual `r2` tree remains to be verified.
- **Recovery and residue:** Reject the terminal path as handoff evidence. Derive the reported path
  from the already boundary-checked resolved output, then verify the existing `r2` manifest and file
  hashes without rebuilding or overwriting it.
- **Correction status:** report derivation now uses the resolved output with a reverse-resolution
  assertion; the existing `r2` manifest and all four payload hashes passed direct verification.
- **Mandatory prevention gate:** Builder completion output must be derived from the same resolved
  destination used for writes and must have a custom-output self-check.

### MTA-OPS-202 — Keep independent preflight evidence in independent invocations

- **Observed failure:** The documentation-only preflight combined ZIP listing, repository inventory,
  required-guide read, incident-ledger read, normative-heading search, Git identity, worktree status,
  and historical lookups in one PowerShell invocation. The read-only command returned usable output,
  but it violated the already-read one-evidence-question-per-invocation rule. No source, product,
  installer, process, VM, WSL, radio, or external state changed.
- **Cause certainty:** certain from the exact orchestration command and the applicable QA guide rule.
- **Disproven alternatives:** No output was masked by a later mutating command and no repository or
  external state changed; this is a process-boundary violation, not evidence of incomplete documents,
  branch state, or ZIP corruption.
- **Recovery and residue:** Preserve the returned factual observations, reject the aggregate command as
  formal evidence, record this incident, and repeat each remaining preflight question independently.
  No cleanup is required.
- **Correction status:** process correction recorded before continuing branch creation or document
  import.
- **Mandatory prevention gate:** Each independently answerable discovery, read, identity check, status
  check, and validation must use its own shell invocation; never combine them for convenience.

### MTA-OPS-203 — Quote PowerShell stash references before Git recovery

- **Observed failure:** The first attempt to restore the preserved incident stash used the literal
  `stash@{0}` without shell quoting. PowerShell altered the argument and Git returned `unknown switch
  'e'` before applying or dropping the stash. No source, branch, product, installer, process, VM,
  WSL, radio, or external state changed.
- **Cause certainty:** certain from the exact rejected command and the unchanged worktree and stash
  inventory.
- **Disproven alternatives:** The stash was not lost, partially applied, or dropped; the failure was
  argument parsing rather than stash corruption or Git repository damage.
- **Recovery and residue:** Preserve `stash@{0}`, verify the clean worktree and unchanged stash list,
  then use the same identity with a quoted argument and `git stash apply` so the source remains
  recoverable. No cleanup is required.
- **Correction status:** quoted apply restored the two incident documents; the stash remains retained
  for later removal only after final verification.
- **Mandatory prevention gate:** PowerShell Git refs containing braces must be passed as one quoted
  scalar and the exact stash identity must be rechecked before any recovery mutation.

### MTA-OPS-204 — Check ignore state before resolving a recovered document

- **Observed failure:** After the quoted stash apply exposed a modify/delete conflict, the first
  conflict-resolution `git add` assumed the recovered `docs/mistakes` files were stageable. The
  repository-wide `/docs/**` ignore rule rejected both paths. No source, branch, product, installer,
  process, VM, WSL, radio, or external state changed.
- **Cause certainty:** certain from the Git rejection and the exact `.gitignore` rule.
- **Disproven alternatives:** The files were present and intact in the worktree; the failure was not
  a missing recovery artifact, conflict loss, or repository corruption.
- **Recovery and residue:** Preserve the recovered files, inspect the ignore rule, and force-add only
  the two exact conflict targets. The conflict is resolved as added files; no unrelated ignored path
  was staged.
- **Correction status:** exact-path `git add -f` completed and status shows only the two required
  incident documents staged; the stash remains retained.
- **Mandatory prevention gate:** Before staging imported or recovered documentation, check its ignore
  status and use `git add -f` only for explicitly verified, in-scope paths.

### MTA-OPS-205 — Do not assume the documentation validator exists on the base branch

- **Observed failure:** The required `python tools/validate_mistakes_docs.py --write-index` command
  was invoked after creating `Simple-Architecture` from `main`, but `main` has no such file. Python
  returned a missing-file error before validation or index generation. No source, branch, product,
  installer, process, VM, WSL, radio, or external state changed.
- **Cause certainty:** certain from Python's exact missing-path diagnostic and the earlier repository
  inventory showing the validator only on the prior feature branch.
- **Disproven alternatives:** The validator did not fail because of Python dependencies, malformed
  documents, or stale content; it was not present at this branch's base commit.
- **Recovery and residue:** Preserve the staged incident documents and stop formal validation at the
  missing tool. Do not substitute an ambient validator or claim the ledger valid without the required
  script; report the base-branch tooling gap as unknown until the tool is restored or provided.
- **Correction status:** failure recorded before resuming ZIP import; no retry has been made.
- **Mandatory prevention gate:** Resolve `tools/validate_mistakes_docs.py` from the current branch
  before invoking it, and fail closed when the required validation tool is absent.

### MTA-OPS-206 — Include ignored paths in imported-document inventories

- **Observed failure:** The first post-extraction inventory queried the ignored directory
  `docs/core-simplification` without `rg -u`, so ripgrep returned no paths and did not qualify the
  import. A corrected untracked-file inventory showed all eight expected documents. No source,
  product, installer, process, VM, WSL, radio, or external state changed.
- **Cause certainty:** certain from the repository-wide `/docs/**` ignore rule and the subsequent
  `rg --files -u` result.
- **Disproven alternatives:** The empty inventory was not evidence of failed extraction, missing ZIP
  members, or an empty directory; ignore filtering hid the files.
- **Recovery and residue:** Reject the empty inventory as evidence, preserve the extracted files, and
  re-run the same bounded inventory with `-u`. No cleanup is required.
- **Correction status:** the corrected inventory returned all eight expected ZIP members; no retry of
  extraction was made.
- **Mandatory prevention gate:** Any inventory of a newly imported or ignored path must explicitly
  include ignored files and must be checked against the expected member list before staging.

### MTA-OPS-207 — Apply exact-path force staging to ignored incident documents

- **Observed failure:** The final explicit staging command included the already-identified ignored
  `docs/mistakes` paths without `-f`. Git reported that directory as ignored while staging the ZIP
  documents and other requested files. The previously staged incident files remained staged; no
  source, branch, product, installer, process, VM, WSL, radio, or external state changed.
- **Cause certainty:** certain from Git's ignore diagnostic and the unchanged final status shape.
- **Disproven alternatives:** The imported documents were not lost or skipped, and the incident files
  were not removed from the index; this was a redundant staging invocation with an incomplete option.
- **Recovery and residue:** Preserve the partial staging state and force-stage only the two exact
  ignored incident paths. No broad ignored-tree staging or cleanup is permitted.
- **Correction status:** the requested files are present in the index; the final exact-path staging
  correction remains the only required recovery action.
- **Mandatory prevention gate:** Carry the verified ignore decision into every later staging command;
  once a required path is known ignored, use `git add -f -- <exact-path>` consistently.

### MTA-OPS-208 — Preserve the exact range-read invocation after a wrapper syntax failure

- **Observed failure:** A required 150-line range read for `MISTAKES_TO_AVOID.md` was submitted
  through the orchestration wrapper with malformed JavaScript and returned a wrapper syntax error
  before PowerShell started. No source, branch, product, installer, process, VM, WSL, radio, or
  external state changed.
- **Cause certainty:** certain from the wrapper's `SyntaxError` and the absence of command output.
- **Disproven alternatives:** The failure does not indicate a missing document, invalid PowerShell,
  or incomplete repository state; the shell command was never executed.
- **Recovery and residue:** Reject that range as unread, preserve the staged state, and retry only the
  same bounded range-read operation with a syntactically valid wrapper call. No cleanup is required.
- **Correction status:** incident recorded before resuming the mandatory complete read.
- **Mandatory prevention gate:** Validate the orchestration call shape before dispatch and treat a
  wrapper syntax error as zero evidence from the requested shell operation.

### MTA-OPS-209 — Treat repeated range-read wrapper failures as recurrence

- **Observed failure:** A second required 150-line range read for `MISTAKES_TO_AVOID.md` again
  returned the orchestration wrapper's `SyntaxError` before PowerShell started, after the same class
  had already been recorded as MTA-OPS-208. No source, branch, product, installer, process, VM, WSL,
  radio, or external state changed.
- **Cause certainty:** certain from the repeated wrapper diagnostic and absence of shell output.
- **Disproven alternatives:** The requested document and range were not shown to be missing or invalid;
  the wrapper failed before the command could inspect them.
- **Recovery and residue:** Preserve the staged state, record this recurrence, and use the minimal
  wrapper call shape for the exact unread range. No cleanup is required.
- **Correction status:** recurrence recorded before another read attempt.
- **Mandatory prevention gate:** After one wrapper syntax failure, use a minimal known-valid invocation
  template and do not keep resubmitting the original argument shape.

### MTA-OPS-210 — Bound repository inventories before consuming their output

- **Observed failure:** A broad `rg --files` inventory over tools, tests, scripts, source, and docs
  exceeded the output boundary and was truncated. No source, branch, product, installer, process,
  VM, WSL, radio, or external state changed.
- **Cause certainty:** certain from the command's truncation diagnostic and the oversized aggregate
  inventory scope.
- **Disproven alternatives:** The truncated result does not prove any path is absent or present; it
  is an output-selection failure, not repository evidence.
- **Recovery and residue:** Discard the aggregate output, preserve the staged state, and query only
  the exact allowed file classes or directories required for the current work packet. No cleanup is
  required.
- **Correction status:** incident recorded before continuing A1 path discovery.
- **Mandatory prevention gate:** Use bounded `rg --files` calls with explicit `-g` filters and one
  narrow source area; a truncated inventory is unknown and cannot authorize a read or mutation.

### MTA-OPS-211 — Make generated index paths independent of invocation form

- **Observed failure:** The A1 policy test found that `render_index()` emitted an absolute archive
  path when passed an absolute `Path`, while the generated default index recorded the relative path.
  The index was therefore not deterministic across equivalent callers. No runtime, installer, relay,
  hardware, or external state changed.
- **Cause certainty:** certain from the exact assertion diff and the two path forms.
- **Disproven alternatives:** The archive bytes, extracted headings, and line numbers were unchanged;
  only generator metadata formatting varied with the caller's path representation.
- **Recovery and residue:** Preserve the failing test output, normalize the canonical archive label
  to the repository-relative path, regenerate the index, and rerun the focused policy test. No cleanup
  is required.
- **Correction status:** correction is pending; A1 remains incomplete until the focused test passes.
- **Mandatory prevention gate:** Deterministic generators must normalize equivalent absolute and
  relative inputs before rendering metadata, with a test exercising both call forms.

### MTA-OPS-212 — Isolate staged A1 files before an incident-only commit

- **Observed failure:** The incident-only commit also included the already-staged A1 archive rename
  because the prior `git mv` remained in the index. The archive move was byte-for-byte correct, but
  the intended commit boundary was not. No runtime, installer, relay, hardware, or external state
  changed.
- **Cause certainty:** certain from the commit summary showing the rename alongside the incident
  update and the subsequent status showing only remaining A1 files.
- **Disproven alternatives:** No A1 content was lost or rewritten and no unrelated production path
  was staged; this was commit-scope contamination, not archive corruption.
- **Recovery and residue:** Preserve the completed archive rename, record the boundary mistake, and
  continue without history rewriting. The remaining A1 files will be staged and committed as the A1
  implementation; later A2/A3 boundaries remain separate.
- **Correction status:** incident recorded before continuing the A1 commit.
- **Mandatory prevention gate:** Before every commit, inspect the complete staged name list and
  confirm it contains only the current packet; never rely on the last staging command's intent.

### MTA-OPS-213 — Align contract tests with the implementation's canonical path constant

- **Observed failure:** The first A2 hot-deploy contract test expected the literal
  `/opt/switchtrade-dev/releases/`, while the implementation correctly derives that path from its
  `OverlayRoot` constant. Four other contract tests passed; no WSL, runtime, installer, relay,
  hardware, or external state changed.
- **Cause certainty:** certain from the assertion and the implementation source.
- **Disproven alternatives:** The overlay root was not missing or wrong; the failure was confined to
  a brittle test literal that duplicated an implementation value.
- **Recovery and residue:** Preserve the implementation, update the test to assert the canonical
  constant and its release composition, then rerun the focused contract test. No cleanup is required.
- **Correction status:** correction is pending; A2 remains incomplete until the focused test passes.
- **Mandatory prevention gate:** Contract tests should assert the named source-of-truth constant and
  its composition rather than duplicating a derived literal.

### MTA-OPS-214 — Cover every derived overlay path through its source constant

- **Observed failure:** After correcting the release-path assertion, the A2 contract test failed on
  the same brittle expectation for `/opt/switchtrade-dev/current`. The implementation derives that
  path from `OverlayRoot`; four other contract tests passed and no WSL, runtime, installer, relay,
  hardware, or external state changed.
- **Cause certainty:** certain from the assertion and implementation source.
- **Disproven alternatives:** The current-link path was not incorrect; the test again duplicated a
  derived literal instead of checking the canonical composition.
- **Recovery and residue:** Preserve the implementation, replace the remaining literal assertion
  with the `OverlayRoot` composition, and rerun the focused contract test. No cleanup is required.
- **Correction status:** correction is pending; A2 remains incomplete until the focused test passes.
- **Mandatory prevention gate:** When testing path constants, assert both the root constant and the
  exact suffix/composition used by the implementation, not repeated absolute literals.
