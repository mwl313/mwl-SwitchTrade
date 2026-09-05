# Active incident ledger

This file receives current incidents. Earlier history is immutable evidence in
[`../archive/MISTAKES_TO_AVOID-legacy-20260901.md`](../archive/MISTAKES_TO_AVOID-legacy-20260901.md).
Search [`../INDEX.md`](../INDEX.md) by the exact subsystem, stable error code, failure path, or
recovery path; append new entries here without reordering or renumbering existing evidence.

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

### MTA-DEV-021 — Preserve PowerShell module-mock output before trusting a behavior test

- **Observed failure:** The first no-WSL sync behavior test exited zero but produced no JSON outcome
  for its Python harness. The test therefore could not prove new-release, same-release, changed-release,
  or repeated-run behavior. No WSL, installed runtime, installer, product, or production path changed.
- **Cause certainty:** investigating. The module-scope mock or its output boundary did not reach the
  outer process as expected; the empty stdout is insufficient to identify which boundary owns the loss.
- **Disproven alternatives:** This result does not prove that sync is idempotent or that the overlay
  lifecycle is broken; the intended observation never reached the test harness.
- **Recovery and residue:** Preserve the focused test output, replace the opaque module mock with a
  directly observable behavior seam, and rerun only after the replacement emits a deterministic result.
  No runtime cleanup is required.
- **Correction status:** pending.
- **Mandatory prevention gate:** A process-layer behavior test must assert its own observable result
  before using that result to claim a mocked lifecycle transition.

### MTA-DEV-022 — Forwarded child output must target the caller's redirected streams

- **Observed failure:** The first interactive-process test did not receive the child `ready` line from
  `Invoke-DevInteractiveProcess` before the child exited. No WSL, installed runtime, installer,
  product, or production path changed.
- **Cause certainty:** investigating. Disabling .NET stream redirection alone did not establish an
  observable parent-pipe contract for the PowerShell caller.
- **Disproven alternatives:** The failure is not evidence that the child did not print or that a WSL
  runtime is unavailable; it proves only that this helper did not forward output through the tested
  redirected boundary.
- **Recovery and residue:** Preserve the first test result and use explicit asynchronous forwarding for
  stdout and stderr, then rerun the focused output-timing test. No runtime cleanup is required.
- **Correction status:** pending.
- **Mandatory prevention gate:** Long-running command helpers must have a timing test that observes
  stdout before child exit through the same caller boundary used by the CLI.

### MTA-DEV-023 — Resolve module paths before using a PowerShell module session

- **Observed failure:** A focused module-session probe passed the relative module path
  `scripts\\dev\\DevOverlay.psm1` to `Import-Module -Name` and PowerShell did not load it. The probe
  therefore could not establish a module-scoped output boundary. No WSL, installed runtime, installer,
  product, or production path changed.
- **Cause certainty:** certain. `Import-Module -Name` searched module locations instead of treating the
  relative string as the observed file path.
- **Disproven alternatives:** This does not explain the earlier absolute-path behavior-test output loss;
  the failed probe used a different, invalid import boundary.
- **Recovery and residue:** Reject the probe and use the already-resolved absolute module path for all
  module-session tests. No runtime cleanup is required.
- **Correction status:** recorded before the next focused probe.
- **Mandatory prevention gate:** A PowerShell module-session test must pass a resolved file path to
  `Import-Module`; do not infer that `-Name` resolves arbitrary relative module paths.

### MTA-DEV-024 — Anchor same-signature PowerShell helper patches to the exact function

- **Observed failure:** The first interactive-I/O patch matched the shared process-start setup in the
  captured helper, duplicating its redirection assignments while leaving the interactive helper without
  the required redirection. No command process, WSL, installed runtime, installer, product, or
  production path was started or changed.
- **Cause certainty:** certain from the immediate bounded source inspection after the patch.
- **Disproven alternatives:** The duplicate lines do not indicate a .NET I/O behavior change; this is
  a patch-anchor error before any interactive command was executed.
- **Recovery and residue:** Preserve the incorrect diff, correct only the duplicated captured lines
  and the interactive helper's explicit redirection, then parse before running the focused test again.
  No runtime cleanup is required.
- **Correction status:** pending.
- **Mandatory prevention gate:** When adjacent helpers share setup statements, patch against the exact
  function body and inspect that bounded body before invoking a behavioral test.

### MTA-DEV-025 — Preserve collection shape in single-source overlay behavior tests

- **Observed failure:** The no-WSL lifecycle mock returned one source path through an unwrapped
  PowerShell pipeline. Under strict mode, the resulting scalar lacked an expected `Count` property,
  so the test never produced its lifecycle result. No WSL, installed runtime, installer, product, or
  production path changed.
- **Cause certainty:** certain from the repeated `PropertyNotFoundException` diagnostics and the
  single-item mock return shape.
- **Disproven alternatives:** This failure does not prove an overlay transition error; it prevented
  the test from reaching the mocked release checks.
- **Recovery and residue:** Preserve the stderr and make the mock's one-path result an explicit array,
  then rerun the focused lifecycle test. No runtime cleanup is required.
- **Correction status:** pending.
- **Mandatory prevention gate:** PowerShell behavior tests must exercise zero, one, and many collection
  shapes wherever the implementation reads `Count` or indexes a command result.

### MTA-DEV-026 — Do not assume PowerShell event callbacks forward child streams

- **Observed failure:** Replacing inherited handles with `OutputDataReceived` and `ErrorDataReceived`
  callbacks still left the interactive timing test without the child `ready` line before exit. No WSL,
  installed runtime, installer, product, or production path changed.
- **Cause certainty:** certain that this callback implementation failed the caller-pipe contract;
  investigating which PowerShell callback boundary suppressed the stream.
- **Disproven alternatives:** The result does not show that the child was silent or that WSL is at
  fault; the direct Python child remains the only process under test.
- **Recovery and residue:** Preserve the failed timing result and use explicit asynchronous stream-copy
  tasks rather than PowerShell event callbacks, then rerun only the focused timing test. No runtime
  cleanup is required.
- **Correction status:** pending.
- **Mandatory prevention gate:** A stream-forwarding implementation must be proven through a redirected
  caller pipe; callback registration alone is not acceptance evidence.

### MTA-DEV-027 — Console stream copies are not a PowerShell pipeline contract

- **Observed failure:** The second interactive-I/O correction copied the child byte streams to
  `Console.OpenStandardOutput()` and `Console.OpenStandardError()`, but the redirected-caller timing
  test still received no `ready` line before exit. No WSL, installed runtime, installer, product, or
  production path changed.
- **Cause certainty:** certain that this copy target failed the tested output contract; the exact host
  mapping between Console streams and PowerShell's pipeline remains irrelevant to the required result.
- **Disproven alternatives:** The successful mocked sync lifecycle and the direct Python child exclude
  overlay identity and WSL discovery as causes of this timing failure.
- **Recovery and residue:** Preserve the timing failure and use a PowerShell pipeline reader that emits
  each stdout/stderr line to the caller, then rerun the focused timing test. No runtime cleanup is
  required.
- **Correction status:** pending.
- **Mandatory prevention gate:** Interactive process output must be delivered through the same
  PowerShell output/error channels the CLI caller redirects and observes.

### MTA-DEV-028 — Verify the interactive helper's callable boundary before diagnosing its stream

- **Observed failure:** The pipeline-reader correction still produced no `ready` line in the timing
  test. The test had not yet separately proven that its imported module exposed and invoked the exact
  helper body. No WSL, installed runtime, installer, product, or production path changed.
- **Cause certainty:** investigating. The failed observation proves the timing contract remains unmet,
  but not whether the loss occurs in module export, helper invocation, or line forwarding.
- **Disproven alternatives:** The no-WSL sync lifecycle test now passes, so this does not invalidate
  the release reuse correction.
- **Recovery and residue:** Preserve the focused failure, probe the module's exported command identity
  and capture its stderr before changing the stream implementation again. No runtime cleanup is
  required.
- **Correction status:** pending.
- **Mandatory prevention gate:** A subprocess timing test must independently prove the exact helper is
  callable before attributing an empty stream to the helper's I/O algorithm.

### MTA-DEV-029 — Test private module helpers through the module session

- **Observed failure:** The callable-boundary probe confirmed that `Invoke-DevInteractiveProcess` is
  private to `DevOverlay.psm1` and is not exported by `Import-Module`. The timing test had invoked an
  unrecognized command rather than the helper. No WSL, installed runtime, installer, product, or
  production path changed.
- **Cause certainty:** certain from `Get-Command` after importing the resolved module path.
- **Disproven alternatives:** The preceding empty timing observations do not diagnose the helper's
  stream forwarding because the test never reached it.
- **Recovery and residue:** Preserve the probe result and invoke the private helper inside the imported
  module session, then rerun the timing test. No runtime cleanup is required.
- **Correction status:** pending.
- **Mandatory prevention gate:** Tests of private PowerShell module functions must use the module's
  session invocation boundary or test an explicitly exported public command.

### MTA-DEV-030 — Close subprocess pipes after interactive timing assertions

- **Observed failure:** The corrected interactive timing test passed but emitted `ResourceWarning` for
  its unclosed stdout and stderr pipe wrappers. No WSL, installed runtime, installer, product, or
  production path changed.
- **Cause certainty:** certain from Python's warning, which named both unclosed pipe wrappers.
- **Disproven alternatives:** The warning does not invalidate the passing child output timing result;
  it identifies missing test-harness cleanup only.
- **Recovery and residue:** Close both pipes after collecting exit and stderr evidence, then rerun the
  focused test without warnings. No runtime cleanup is required.
- **Correction status:** pending.
- **Mandatory prevention gate:** Subprocess timing tests must close every redirected pipe after the
  terminal process result is observed.

### MTA-OPS-215 — Keep every multi-file patch hunk syntactically complete

- **Observed failure:** A combined documentation patch omitted a hunk prefix on one continuation line,
  and `apply_patch` rejected it before any target file changed. No WSL, installed runtime, installer,
  product, or production path changed.
- **Cause certainty:** certain from the patch parser's invalid-hunk diagnostic.
- **Disproven alternatives:** The rejection does not indicate a routing-content conflict or partial
  documentation update; no hunk was applied.
- **Recovery and residue:** Preserve the rejected patch result and apply each verified document change
  in a separate complete hunk. No runtime cleanup is required.
- **Correction status:** pending.
- **Mandatory prevention gate:** Before submitting a multi-file patch, ensure every changed or context
  line has its required patch prefix and split unrelated documents into separate patch operations.

### MTA-OPS-216 — Stage renamed paths by their present index or worktree identity

- **Observed failure:** The first exact-path staging command included the old
  `docs/mistakes/INCIDENTS.md` name after `git mv` had already removed that worktree path. Git rejected
  the pathspec, and no successful staging result was inferred. No WSL, installed runtime, installer,
  product, or production path changed.
- **Cause certainty:** certain from Git's exact pathspec diagnostic and the already-observed rename
  status.
- **Disproven alternatives:** The incident ledger was not lost; its destination exists at
  `docs/incidents/current/INCIDENTS.md`. This is a staging identity error, not a documentation move
  failure.
- **Recovery and residue:** Preserve the rejected command and stage only existing worktree paths while
  retaining the already-indexed rename. No runtime cleanup is required.
- **Correction status:** pending.
- **Mandatory prevention gate:** Before staging a renamed file, use its current destination path or
  rely on the existing index entry; never include an absent historical source path in a pathspec.

### MTA-OPS-217 — Force-stage verified ignored documentation paths

- **Observed failure:** The corrected exact-path staging command still omitted `-f` for the repository's
  verified `/docs/**` ignore rule, so Git rejected the active routing and incident paths. No successful
  staging result was inferred. No WSL, installed runtime, installer, product, or production path
  changed.
- **Cause certainty:** certain from Git's ignored-path diagnostic and the earlier exact ignore-state
  evidence for this documentation tree.
- **Disproven alternatives:** The paths are intentional current repository documents, not accidental
  generated artifacts or unrelated ignored files.
- **Recovery and residue:** Preserve the rejection and force-stage only the enumerated in-scope
  documentation paths; no broad ignored-tree add is permitted. No runtime cleanup is required.
- **Correction status:** pending.
- **Mandatory prevention gate:** Once a required documentation path is known to be ignored, every
  staging command for that exact path must use `git add -f -- <verified paths>`.

### MTA-OPS-218 — Do not restage an already-indexed deletion by an absent path

- **Observed failure:** A force-staging command included the old ignored index path after an earlier
  `git add -A` had already placed its deletion in the index. Git rejected the now-absent pathspec.
  No successful staging result was inferred. No WSL, installed runtime, installer, product, or
  production path changed.
- **Cause certainty:** certain from the exact pathspec diagnostic and the prior staged deletion state.
- **Disproven alternatives:** The old index was not restored or lost; it is intentionally superseded by
  the generated unified `docs/incidents/INDEX.md`.
- **Recovery and residue:** Preserve the rejected command, leave the existing deletion index entry
  intact, and force-stage only present active documentation paths. No runtime cleanup is required.
- **Correction status:** pending.
- **Mandatory prevention gate:** For a path already staged as deleted, verify staged state instead of
  including its absent historical name in another `git add` pathspec.

### MTA-OPS-219 — Read dependency locks by the required package entry

- **Observed failure:** A Phase B dependency inspection read the complete hash-locked relay
  requirements file when only FastAPI availability was relevant. The output was truncated and cannot
  serve as complete lock-file evidence. No source, WSL, installed runtime, installer, product, or
  production path changed.
- **Cause certainty:** certain from the tool's truncation diagnostic and the oversized hash lock.
- **Disproven alternatives:** The visible FastAPI entry remains a valid narrow observation; the
  truncated output does not establish the rest of the lock's contents or compatibility.
- **Recovery and residue:** Discard the aggregate lock output and query only named package entries in
  future dependency checks. No runtime cleanup is required.
- **Correction status:** recorded before Phase B implementation proceeds.
- **Mandatory prevention gate:** For a hash-locked dependency file, search the exact required package
  name instead of reading the full lock unless the entire lock is itself the scoped evidence.

### MTA-OPS-220 — Run package tests through the repository import boundary

- **Observed failure:** The first Phase B contract test was executed as a file, so Python placed
  `tests/` rather than the repository root on `sys.path` and could not import `switchtrade`. No source,
  relay process, WSL, installed runtime, installer, or product state changed.
- **Cause certainty:** certain from `ModuleNotFoundError: No module named 'switchtrade'` before test
  collection.
- **Disproven alternatives:** The result does not indicate a missing Core package or failed fake
  endpoint implementation; imports never reached those modules.
- **Recovery and residue:** Preserve the first traceback and rerun the exact tests with `python -m
  unittest` from the repository root. No runtime cleanup is required.
- **Correction status:** pending.
- **Mandatory prevention gate:** Tests importing repository packages must run through the repository
  module import boundary, not as a bare test-file script.

### MTA-OPS-221 — Retry a wrapper syntax failure with the minimal invocation

- **Observed failure:** The first B1 push wrapper contained malformed orchestration JavaScript and
  failed before PowerShell started Git. No remote branch, source, relay process, WSL, installer, or
  product state changed.
- **Cause certainty:** certain from the wrapper `SyntaxError` and absence of Git output.
- **Disproven alternatives:** The failure does not indicate authentication, remote rejection, or a
  branch divergence; `git push` was never invoked.
- **Recovery and residue:** Preserve the wrapper failure and retry the same explicit branch push with
  a minimal valid wrapper invocation. No runtime cleanup is required.
- **Correction status:** pending.
- **Mandatory prevention gate:** After an orchestration syntax error, remove optional session handling
  and use the smallest known-valid tool call for the exact pending operation.

### MTA-CORE-001 — Do not expose consumed-code state through concurrent join tests

- **Observed failure:** The first B2 concurrent-join test expected the losing request to receive
  `PAIR_CODE_CONSUMED`, but a successfully joined code is removed from the admission map and correctly
  returned `PAIR_CODE_INVALID`. No relay listener, source-managed pair state outside the test process,
  WSL, installer, or product state changed.
- **Cause certainty:** certain from the atomic join path: it assigns the guest, removes the code, and
  only then releases the pair-store lock.
- **Disproven alternatives:** This did not permit a second guest token or indicate a lock failure; the
  test asserted an unpromised state distinction after successful one-time-code consumption.
- **Recovery and residue:** Preserve the failed assertion and require exactly one guest outcome with
  the opaque invalid-code result for the competing request. The in-memory test store is gone.
- **Correction status:** focused pair-store test passed after the expectation correction.
- **Mandatory prevention gate:** Concurrent admission tests must prove the one-guest invariant without
  turning a consumed-code lookup result into an externally observable oracle.

### MTA-OPS-222 — Keep staged diff checks to one evidence question

- **Observed failure:** A B2 staged review combined whitespace, statistics, and status checks in one
  PowerShell invocation. The results named only the intended six files and reported no whitespace
  errors, but the invocation broke the repository's one-evidence-question rule. No relay, WSL,
  installer, product, or external state changed.
- **Cause certainty:** certain from the literal command composition.
- **Disproven alternatives:** The staged content was not altered and the combined output does not
  indicate a source, admission, credential, or Git index defect.
- **Recovery and residue:** Preserve the staged set and repeat the required whitespace and status
  observations in separate invocations before commit. No cleanup is required.
- **Correction status:** pending independent staged review.
- **Mandatory prevention gate:** Keep each staged-diff, staged-statistics, and status observation in
  its own shell invocation even when all use the same Git index.

### MTA-CORE-002 — Reconnect must not rotate the peer source epoch

- **Observed failure:** B3 review identified that accepting a new peer epoch called local `start()`,
  allowing alternating reconnects to create an epoch-restart ping-pong. The reviewed source had not
  been deployed or connected to a product endpoint.
- **Cause certainty:** certain from the state transition: each accepted new epoch emitted another
  local `PEER_READY`, which the peer treats as a new source epoch in turn.
- **Disproven alternatives:** Queue replacement alone does not prove a two-sided reconnect handshake,
  and the existing one-client test could not exercise this state cycle.
- **Recovery and residue:** Preserve the reviewed state machine, keep the local epoch stable when the
  peer reconnects, reset probe/generation state, and send a new challenge on the current epoch.
- **Correction status:** focused two-sided reconnect and reprobe test passed with the live epoch unchanged.
- **Mandatory prevention gate:** A reconnect test must keep one client live, reconnect the other, and
  prove both probes recover while the live client's epoch remains unchanged.

### MTA-OPS-223 — Patch only against verified local hunk context

- **Observed failure:** The first B3 repair patch contained a stale hunk context and `apply_patch`
  rejected it before changing any source or relay state.
- **Cause certainty:** certain from the patch verifier's exact missing-context diagnostic.
- **Disproven alternatives:** The rejection did not indicate a transport defect or partial source
  mutation; no hunk was applied.
- **Recovery and residue:** Preserve the rejection, use the immediately observed file text as the
  patch context, and reapply the repair. No cleanup is required.
- **Correction status:** verified-context repair patch applied.
- **Mandatory prevention gate:** For every multi-hunk repair, match each hunk against the latest
  bounded source read rather than reconstructed context.

### MTA-CORE-003 — Wait for the transport failure signal, not a scheduler guess

- **Observed failure:** The first B3 send-timeout test slept for a fixed short interval and then
  expected a failed client; the event-loop schedule had not made that observation deterministic.
  No relay listener, product socket, WSL, or endpoint resource was created.
- **Cause certainty:** certain from the assertion: the test checked client state without awaiting the
  transport's own failure event.
- **Disproven alternatives:** The result does not prove that timeout handling is absent or that the
  bounded writer loop delivered a frame; it only invalidates the timing-based test observation.
- **Recovery and residue:** Preserve the failed assertion and wait on the client failure event with a
  bounded timeout before asserting the public failure code. The in-memory socket is disposable.
- **Correction status:** focused transport rerun passed after awaiting the failure event.
- **Mandatory prevention gate:** Async failure tests must await their explicit failure/completion signal
  under a timeout; never infer a state transition from an arbitrary scheduler sleep.

### MTA-CORE-004 — Resync both epochs when reconnect drops a contiguous frame

- **Observed failure:** B3 review found that discarding a reconnect-time pending frame while retaining
  the live peer's source epoch leaves the returning client expecting a missing sequence before the
  new probe arrives. No product endpoint, relay listener, or external socket was started.
- **Cause certainty:** certain from the sequence contract: the sender advances H1 while the receiver
  never observes the discarded H1 frame, so the next H1 probe is a gap.
- **Disproven alternatives:** Queue replacement and a no-traffic reconnect do not prove recovery
  after a dropped frame; they omit the sequence divergence that causes this failure.
- **Recovery and residue:** On a reconnect, rotate each source epoch exactly once: the reconnecting
  side expects its peer's resync, and the live side rotates only after accepting that new peer epoch.
- **Correction status:** dropped-DATA two-sided reconnect, reprobe, and new-generation regression passed.
- **Mandatory prevention gate:** Reconnect regression must drop at least one live peer frame before
  the returning socket reprobes, then prove fresh epoch zero ordering and no sequence gap.

### MTA-OPS-224 — Verify package-root paths before a multi-file patch

- **Observed failure:** The first B4 supervisor patch targeted `core/__init__.py` rather than the
  observed `switchtrade/core/__init__.py`; `apply_patch` rejected the operation before any file
  changed.
- **Cause certainty:** certain from the missing-path diagnostic and the immediately preceding source
  inventory.
- **Disproven alternatives:** This rejection does not indicate a Core or transport failure and did
  not create a supervisor, test, process, or endpoint state.
- **Recovery and residue:** Preserve the rejection, use the verified package-root path, and split the
  patch by file. No cleanup is required.
- **Correction status:** verified-path B4 patch applied.
- **Mandatory prevention gate:** Before every multi-file package patch, compare each target path with
  the current bounded inventory rather than reconstructing a shortened package path.

### MTA-CORE-005 — Assert asynchronous packet delivery from its completion signal

- **Observed failure:** The first B4 supervisor pump regression put packets into both local test
  generations, yielded once with `sleep(0)`, and asserted delivery. One relay pump had not yet run,
  so the assertion observed an empty mirror send list. No product endpoint, relay listener, or
  external socket was created.
- **Cause certainty:** certain from the failed assertion and the queued test packet: the test used a
  scheduler guess instead of the generation's packet-delivery signal.
- **Disproven alternatives:** The result does not establish a broken Core pump or an invalid wire
  frame; it only invalidates the timing-dependent observation.
- **Recovery and residue:** Preserve the failed assertion and wait under a bounded timeout for the
  receiving fake generation to record the expected packet. The in-memory queues are disposable.
- **Correction status:** signal-bound B4 pump regression passed.
- **Mandatory prevention gate:** Async delivery tests must await a bounded completion signal or
  state predicate; never use a single event-loop yield as delivery proof.

### MTA-OPS-225 — Search only verified task-document paths

- **Observed failure:** A B4 documentation search included the unobserved path
  `docs/core-simplification/TODO.md`. Ripgrep reported that operand missing, so the combined result
  is not valid evidence for the requested task-document check. No product state changed.
- **Cause certainty:** certain from ripgrep's exact missing-path diagnostic.
- **Disproven alternatives:** The error does not establish that a TODO document is absent elsewhere
  or that the already-read B4 design and prompt are invalid.
- **Recovery and residue:** Preserve the diagnostic and discard the combined search as evidence; use
  only previously verified paths or discover the exact document path before a future search.
- **Correction status:** verified B4 prompt/design paths retained; no retry against a guessed path.
- **Mandatory prevention gate:** Every task-document operand in a scoped search must be observed in a
  bounded inventory or supplied verbatim by the user before use.

### MTA-OPS-226 — Discover transport module names before direct inspection

- **Observed failure:** A B4 Core review attempted to read the unobserved module path
  `switchtrade/transport/state.py`; PowerShell reported it missing. The same invocation did read
  the already-known Core contracts, but no conclusion was drawn from the missing transport operand.
- **Cause certainty:** certain from the exact missing-path diagnostic.
- **Disproven alternatives:** This does not prove that transport state is missing or that B4 state
  transitions are invalid; only the guessed filename was invalid.
- **Recovery and residue:** Preserve and discard the transport portion of that read, then inventory
  the narrow transport directory before inspecting its state implementation. No product state changed.
- **Correction status:** bounded transport module inventory completed before inspection.
- **Mandatory prevention gate:** Before directly opening an unobserved source module, resolve its
  exact filename with a bounded `rg --files` inventory.

### MTA-OPS-227 — Do not infer a relay package location from its import name

- **Observed failure:** A B4 dependency inventory included the unobserved directory
  `switchtrade/relay`; ripgrep reported that operand missing. The result therefore cannot establish
  the implementation location of the existing relay API or pair service. No product state changed.
- **Cause certainty:** certain from ripgrep's exact missing-directory diagnostic.
- **Disproven alternatives:** The error does not show that relay functionality is absent; only the
  package layout assumption was unsupported.
- **Recovery and residue:** Preserve and discard that combined inventory, then start from a verified
  package-wide file list before selecting a relay-related module. No cleanup is required.
- **Correction status:** package-wide bounded inventory completed before selecting relay files.
- **Mandatory prevention gate:** Treat an import-domain name as an API boundary, not a filesystem
  path; resolve its implementation from a verified file inventory before searching it.

### MTA-CORE-006 — Preserve terminal failure state across generation cleanup

- **Observed failure:** The new B4 local-generation failure regression proved that the pump recorded
  `S_PUMP_FAILED` and closed the generation, but `close_generation()` overwrote `FAILED` with
  `CLOSING_GENERATION` before returning. No product endpoint, relay listener, or external socket
  was created.
- **Cause certainty:** certain from the assertion and the cleanup path: a pre-existing first failure
  skips the normal `PAIRED` assignment without restoring its terminal state.
- **Disproven alternatives:** This is not an incomplete cleanup result; the local generation's close
  completion signal was observed before the state assertion.
- **Recovery and residue:** Preserve the failed state assertion and assign `FAILED` after a clean
  close when a first functional failure exists. The in-memory generation is closed.
- **Correction status:** terminal-state restoration regression passed.
- **Mandatory prevention gate:** Every cleanup path reachable after a recorded failure must assert
  both resource closure and the final public `FAILED` state.

### MTA-OPS-228 — Bound the legacy full-suite wait and clean up owned test processes

- **Observed failure:** The B4 final `unittest discover -s tests` run remained live beyond two
  bounded 30-second waits without a terminal summary. The verified owned parent/child process IDs
  were 26220 and 20068. B4's focused supervisor and Core suites had already completed successfully.
- **Cause certainty:** certain that the full-suite invocation exceeded the bound, from the verified
  live process IDs; uncertain which legacy integration test held the process without an isolated
  timeout run.
- **Disproven alternatives:** This does not invalidate the passing B4 tests or prove a B4 failure;
  no B4 test was identified as the stalled case.
- **Recovery and residue:** Preserve the incomplete run, terminate only the exact owned test parent
  and child, then verify no matching discovery process remains. Do not represent the full suite as
  passing.
- **Correction status:** verified no matching owned discovery process remains.
- **Mandatory prevention gate:** Full repository test runs must have a bounded completion check; on
  timeout, record the exact owned process identity, clean it up, and isolate the holding test before
  retrying the broad suite.

### MTA-OPS-229 — Force-stage ignored incident documents with the implementation packet

- **Observed failure:** The first B4 staging command named the two incident documents without
  `-f`. Git staged the Core source and test paths but rejected `docs/incidents` under the repository
  ignore rule, leaving a partial packet.
- **Cause certainty:** certain from Git's ignored-path diagnostic and the explicit staging output.
- **Disproven alternatives:** The source/test staging did not include the required incident ledger or
  generated index, so the partial index cannot authorize a commit.
- **Recovery and residue:** Preserve the partial staging, regenerate the index after recording this
  incident, then force-stage only the two verified ignored incident paths and inspect the complete
  staged name list before commit.
- **Correction status:** incident documents force-staged; complete staged name list verified.
- **Mandatory prevention gate:** When a packet changes ignored incident documents, stage those exact
  paths with `git add -f --` in a separate mutation before every commit.

### MTA-OPS-230 — Resolve transport regression test filenames before reading

- **Observed failure:** A B4 recovery review attempted to open the unobserved test path
  `tests/test_transport_client.py`; PowerShell reported it missing. The same invocation did read
  the known B4 supervisor test, but no conclusion was drawn from the missing transport operand.
- **Cause certainty:** certain from the exact missing-path diagnostic.
- **Disproven alternatives:** This does not show that the B3 WireClient regressions are absent or
  that reconnect behavior lacks coverage; only the guessed test filename was invalid.
- **Recovery and residue:** Preserve and discard the transport-test portion of the read, then use a
  bounded test-file inventory to resolve the exact B3 test path before inspection. No product state
  changed.
- **Correction status:** bounded transport test inventory completed before inspection.
- **Mandatory prevention gate:** Before reading an unobserved test module, resolve its exact filename
  with a bounded `rg --files tests` inventory.

### MTA-OPS-231 — Apply one patch operation per target file

- **Observed failure:** The first B4 recovery patch contained two separate update operations for
  `switchtrade/transport/wire.py`; `apply_patch` rejected the entire patch before any source file
  changed.
- **Cause certainty:** certain from the patch verifier's duplicate-target diagnostic.
- **Disproven alternatives:** The rejection does not indicate a WireState or supervisor defect and
  did not alter transport, Core, test, or runtime state.
- **Recovery and residue:** Preserve the rejection and split each target into one complete file
  operation based on the already-read source. No cleanup is required.
- **Correction status:** file-separated recovery patch applied.
- **Mandatory prevention gate:** Every `apply_patch` submission must contain at most one update
  operation for a given file; merge its hunks under that one operation before dispatch.

### MTA-CORE-007 — Inject teardown-window DATA only after remote admission stops

- **Observed failure:** The first B4 stale-generation barrier regression inserted a DATA envelope
  immediately before `close_generation()`. The live remote pump sometimes consumed it before close
  canceled that pump, so discard accounting observed zero frames.
- **Cause certainty:** certain from the zero discard count and task scheduling: the test did not
  synchronize insertion with the cleanup window it intended to prove.
- **Disproven alternatives:** This does not show the retirement barrier is absent or that the frame
  reached a subsequent generation; it invalidates the unsynchronized injection point.
- **Recovery and residue:** Preserve the assertion and block `LocalGeneration.close()` after pump
  cancellation, inject DATA into the WireClient queue in that window, then release cleanup.
- **Correction status:** cleanup-window synchronized regression passed.
- **Mandatory prevention gate:** Tests for teardown admission barriers must synchronize against the
  post-cancellation cleanup phase, not merely enqueue a frame before teardown starts.

### MTA-CORE-008 — Cancel WireClient helper waits with their owning receive

- **Observed failure:** The synchronized B4 teardown-window regression still observed zero discard
  count. Canceling the remote pump canceled its outer `WireClient.receive()` coroutine but left that
  method's internal queue-get task live; the orphan consumed the injected old-generation DATA.
- **Cause certainty:** certain from the receive implementation's missing cancellation-finally path
  and the frame disappearing before supervisor drain accounting.
- **Disproven alternatives:** The synchronized result is not a scheduler guess or a missing
  supervisor discard call; the lingering child task bypassed the intended barrier.
- **Recovery and residue:** Preserve the failed assertion, cancel and await all helper wait tasks in
  `receive()` and related wait helpers, then rerun the same synchronized barrier regression.
- **Correction status:** WireClient helper-task cleanup regression passed.
- **Mandatory prevention gate:** Any coroutine that creates helper tasks must cancel and await them
  in a `finally` block when its owning coroutine is canceled.

### MTA-CORE-009 — Let supervisor control the peer's fake-generation close

- **Observed failure:** The first B5 real FastAPI/WebSocket E2E closed the host fake generation and
  waited for the guest supervisor to become `PAIRED`. `FakeGeneration.close()` inserted a sentinel
  into the peer generation's receive queue before the relay `GENERATION_CLOSE` arrived, so the guest
  local pump failed instead of following its control-plane close path.
- **Cause certainty:** certain from the E2E timeout at guest `PAIRED` and the fake endpoint's
  cross-peer sentinel write during local close.
- **Disproven alternatives:** Relay authentication, probe, direct WireClient packet exchange, and
  the first fake offer/accept completed before this cleanup ordering failure.
- **Recovery and residue:** Preserve the failed E2E, make fake close release only its local receive
  wait, and let the supervisor's generation-close frame initiate the peer's local cleanup.
- **Correction status:** real FastAPI/WebSocket E2E clean-close regression passed.
- **Mandatory prevention gate:** Endpoint `close()` must not preempt the peer's supervisor-owned
  control-plane close; E2E close tests must prove the peer returns to `PAIRED` cleanly.

### MTA-OPS-232 — Split mixed-scope source searches before output truncation

- **Observed failure:** A B5 follow-up search combined fake endpoint, archive manifest, and
  DevOverlay terms across tests, source, and the dispatcher. Its output exceeded the boundary and
  was truncated, so the portability-file portion is not valid inspection evidence.
- **Cause certainty:** certain from the tool's truncation notice.
- **Disproven alternatives:** The visible fake endpoint matches are not invalidated, but the
  truncated result cannot establish the complete manifest or DevOverlay test scope.
- **Recovery and residue:** Preserve the incomplete search and use exact, separately bounded file
  reads for the fake endpoint and each named portability test. No product state changed.
- **Correction status:** split fake endpoint and exact portability inspections completed.
- **Mandatory prevention gate:** Do not combine independent subsystem searches when their aggregate
  output can exceed the boundary; inspect each verified source area in a separate bounded call.

### MTA-OPS-233 — Normalize archive manifest before asserting canonical Git bytes

- **Observed failure:** The B5 portability test was changed to inspect the archive's canonical Git
  blob, but the existing manifest still recorded the Windows checkout representation: 190147 bytes
  instead of the blob's 187541 bytes. The focused test failed before any product or release state
  changed.
- **Cause certainty:** certain from the manifest, the focused assertion, and `git show` of the
  named archive blob.
- **Disproven alternatives:** The archive was not missing and Git did not alter the checked-in blob;
  the mismatch is the manifest's former working-tree-byte basis.
- **Recovery and residue:** Preserve the failed focused result, update the manifest to the canonical
  blob byte size and SHA-256, regenerate the incident index, and rerun the focused policy test.
  No cleanup is required.
- **Correction status:** canonical manifest normalization and focused policy rerun passed.
- **Mandatory prevention gate:** When an immutable archive manifest is intended to be cross-platform,
  derive and verify it from the Git blob rather than from a platform checkout.

### MTA-OPS-234 — Force-stage ignored incident documents as a separate mutation

- **Observed failure:** The B5 portability packet used ordinary `git add` for files under
  `docs/incidents`, and Git rejected the ignored document paths. No commit was created from that
  failed staging attempt and no product state changed.
- **Cause certainty:** certain from Git's ignored-path diagnostic and the repository staging rule.
- **Disproven alternatives:** The policy and manifest changes are not absent; ordinary staging is the
  incorrect mutation for these intentionally ignored records.
- **Recovery and residue:** Preserve the rejected staging attempt, force-stage only the named incident
  documents in a separate Git mutation, inspect the staged result, then commit the packet.
- **Correction status:** forced document staging and staged-packet inspection passed.
- **Mandatory prevention gate:** Before committing an incident or index update, use `git add -f --`
  for the exact ignored document paths, separate from ordinary source/test staging.

### MTA-OPS-235 — Read Phase documents in bounded sections

- **Observed failure:** A C1 baseline read combined the master plan with the complete C design and
  prompt, exceeding the output boundary. The result cannot prove that the later C design sections
  were read before implementation.
- **Cause certainty:** certain from the tool truncation notice.
- **Disproven alternatives:** The visible C1 prompt text is valid, but it does not substitute for the
  omitted remainder of the normative C documents.
- **Recovery and residue:** Preserve the incomplete read, regenerate the index, then read the C
  design and prompt in separate bounded sections before inspecting or changing implementation files.
- **Correction status:** C design and prompt read in bounded sections before source inspection.
- **Mandatory prevention gate:** Do not combine complete phase design and prompt documents with the
  master plan when their combined output can exceed the inspection boundary.

### MTA-OPS-236 — Inventory packaging metadata before reading it

- **Observed failure:** C1 source inspection assumed `pyproject.toml` and `requirements.lock` existed
  at the repository root; PowerShell reported both paths missing. No package, runtime, endpoint, or
  hardware state changed.
- **Cause certainty:** certain from the missing-path diagnostics.
- **Disproven alternatives:** The absent guessed paths do not show that dependency metadata is absent;
  only their locations were unverified.
- **Recovery and residue:** Preserve the failed read, regenerate the index, use `rg --files` to locate
  actual packaging and lock files, then inspect only those verified paths.
- **Correction status:** verified packaging inventory completed before metadata inspection.
- **Mandatory prevention gate:** Before reading package metadata or dependency locks, resolve their
  exact names with a bounded repository file inventory.

### MTA-OPS-237 — Assert import boundaries from imports, not capability literals

- **Observed failure:** The first C1 import-boundary test rejected every `switch_ldn` string in Core
  and Relay source. It failed on the endpoint-kind capability literal in Core contracts, although no
  concrete driver import exists. No endpoint, runtime, or hardware action occurred.
- **Cause certainty:** certain from the failing source line and the test's substring predicate.
- **Disproven alternatives:** This does not show a Core-to-driver dependency; the enum value is an
  endpoint-neutral contract required by Phase B.
- **Recovery and residue:** Preserve the failed assertion, regenerate the index, replace the raw
  substring check with an AST inspection of import declarations, then rerun the C1 boundary tests.
- **Correction status:** AST import-boundary assertion and C1 focused regression passed.
- **Mandatory prevention gate:** Dependency-boundary tests must inspect actual imports and permit
  endpoint-neutral identifiers that name a supported endpoint kind.

### MTA-OPS-238 — Run pytest-style dependency tests with pytest

- **Observed failure:** C1 verification used `unittest discover` for `test_dependency_lock.py`, whose
  tests are pytest-style functions. The command ran zero tests and returned failure without changing
  package, endpoint, runtime, or hardware state.
- **Cause certainty:** certain from the test module's function-based definitions and unittest's
  `NO TESTS RAN` result.
- **Disproven alternatives:** This does not show a dependency-lock failure; the selected runner did
  not collect the file's tests.
- **Recovery and residue:** Preserve the zero-test result, regenerate the index, run the exact file
  with pytest, and report only the collected result.
- **Correction status:** pytest dependency-lock verification passed.
- **Mandatory prevention gate:** Resolve the test framework from the target module before selecting
  its runner; unittest discovery does not collect plain pytest test functions.

### MTA-OPS-239 — Resolve GitHub run IDs from the commit before viewing jobs

- **Observed failure:** C1 CI follow-up treated displayed run number 91 as a GitHub Actions database
  ID. `gh run view` returned 404 before reading any job state; no repository, runtime, or endpoint
  state changed.
- **Cause certainty:** certain from the API response and the unverified numeric ID.
- **Disproven alternatives:** The 404 does not indicate a failed CI workflow or missing commit; it
  only rejects the guessed database identifier.
- **Recovery and residue:** Preserve the failed lookup, regenerate the index, list runs by the exact
  C1-fix commit SHA, then view the returned database ID if job detail is needed.
- **Correction status:** commit-bound CI lookup confirmed the C1-fix workflow is in progress.
- **Mandatory prevention gate:** Do not pass a displayed Actions run number to APIs that require a
  database ID; resolve it from the exact commit first.

### MTA-OPS-240 — Assert cancellation cleanup from the report, not annotations

- **Observed failure:** The first C2 cancellation regression patch compared `driver.close()` to its
  return annotation rather than inspecting the returned cleanup report. The invalid assertion was
  caught in source review before a test or endpoint action ran.
- **Cause certainty:** certain from the incompatible comparison in the unexecuted test body.
- **Disproven alternatives:** This does not indicate a cancellation or cleanup defect; no test has
  exercised the new path yet.
- **Recovery and residue:** Preserve the pre-test patch, regenerate the index, assert the concrete
  report fields after cancellation, then run the focused regression.
- **Correction status:** corrected cancellation-report assertion and focused C2 regressions passed.
- **Mandatory prevention gate:** For async cleanup tests, await the operation and assert its concrete
  `CleanupReport` fields; never infer result semantics from function annotations.

### MTA-OPS-241 — Resolve phase-document locations before searching

- **Observed failure:** C3 inspection assumed the planning documents lived under `docs/planning`; the
  bounded search reported both paths missing. No source, endpoint, runtime, or hardware state changed.
- **Cause certainty:** certain from the missing-path diagnostics and the subsequent verified document
  inventory.
- **Disproven alternatives:** The rejected paths do not indicate a missing Phase C design or prompt;
  the documents are stored under `docs/core-simplification`.
- **Recovery and residue:** Preserve the failed lookup, regenerate the index, and use only the verified
  `docs/core-simplification/C_SWITCH_CORE_{DESIGN,PROMPT}.md` paths for C3 work.
- **Correction status:** verified C3 design and prompt sections were read from their actual paths.
- **Mandatory prevention gate:** Before reading a named planning artifact, resolve its exact repository
  location with a bounded file inventory when its directory has not been observed in the current task.

### MTA-OPS-242 — Split same-file replacement patches into separate operations

- **Observed failure:** The first C3 generation-module replacement attempted a delete and add for the
  same path in one `apply_patch` operation; the patch verifier rejected the duplicate target. No
  source file or endpoint state changed.
- **Cause certainty:** certain from the patch verifier's duplicate-target diagnostic.
- **Disproven alternatives:** The rejection does not indicate an implementation or cleanup failure;
  no hunk was applied.
- **Recovery and residue:** Preserve the rejected patch, regenerate the index, then replace the file
  with separate delete and add operations.
- **Correction status:** pending split patch application.
- **Mandatory prevention gate:** When replacing a complete file, use one update operation or separate
  delete and add patch calls; never target the same path twice in one patch.

### MTA-OPS-243 — Review new test imports before execution

- **Observed failure:** A C3 thread-safety regression used `asyncio.to_thread` without importing
  `asyncio`; source review caught the undefined name before test execution. No endpoint, runtime, or
  hardware state changed.
- **Cause certainty:** certain from the added test body and missing module import.
- **Disproven alternatives:** This does not indicate a CoreTunnelAdapter threading defect; the test
  had not run.
- **Recovery and residue:** Preserve the pre-test finding, regenerate the index, add the explicit
  import, then run the focused adapter regression.
- **Correction status:** import added; focused verification pending.
- **Mandatory prevention gate:** Before running a newly added test module, compare every module
  reference in its new test body against its explicit imports.

### MTA-OPS-244 — Do not overlap full pytest runs that own the relay writer lock

- **Observed failure:** A second C3 full-suite invocation reached relay test collection while the
  first verified `.audit-venv` pytest process, PID 1996 with its child PID 35376, still owned the
  identity-bound relay writer lock. Collection raised `AlreadyRunningError` before executing a test.
- **Cause certainty:** certain from both exact process command lines (`python -m pytest -q`) and the
  lock's `switchtrade-relay-writer-f7314b28fe5cc39a` identity in the collection traceback.
- **Disproven alternatives:** This does not indicate a relay, CoreTunnelAdapter, or test assertion
  defect; the overlapping local test processes conflicted on the deliberate single-writer guard.
- **Recovery and residue:** Preserve the collection traceback and process identities, terminate only
  the exact recorded pytest parent/child if they remain live, prove both are absent, then run one
  full suite and wait for its recorded completion before any retry.
- **Correction status:** identity-bound process cleanup and one-suite retry pending.
- **Mandatory prevention gate:** Capture and retain the terminal session identifier for a full pytest
  run; never launch a second full suite until that exact process has exited and released its relay lock.

### MTA-OPS-245 — Revalidate a recorded recovery PID immediately before termination

- **Observed failure:** The identity-bound C3 recovery attempted to stop recorded pytest PID 1996,
  but it had exited naturally between the identity read and the termination command. PowerShell
  rejected the absent PID; no process was terminated.
- **Cause certainty:** certain from the `Cannot find a process` response after the prior exact process
  observation.
- **Disproven alternatives:** This does not show PID reuse, an incorrect test process identity, or a
  failed cleanup action; it records an ordinary process-exit race.
- **Recovery and residue:** Preserve the absent-PID response, regenerate the index, re-read the exact
  PID set and lock availability, and terminate only a still-live identity match before retrying.
- **Correction status:** live-process and lock revalidation pending.
- **Mandatory prevention gate:** Immediately before any identity-bound process termination, perform a
  fresh exact PID and command-line read; an already-exited PID requires no destructive recovery.

### MTA-OPS-246 — Re-read concurrent-boundary source before a multi-hunk patch

- **Observed failure:** The first C3 lifecycle repair patch used a reconstructed `receive_for_core`
  hunk that did not match the current CoreTunnelAdapter ordering. `apply_patch` rejected it before
  changing source or runtime state.
- **Cause certainty:** certain from the verifier's missing-context diagnostic.
- **Disproven alternatives:** The rejection does not indicate an adapter lifecycle or flag-bound
  defect; no code hunk was applied.
- **Recovery and residue:** Preserve the rejected patch, regenerate the index, read the exact bounded
  adapter source, then apply each lifecycle change against that observed context.
- **Correction status:** exact source re-read pending.
- **Mandatory prevention gate:** Before patching a concurrent boundary with multiple hunks, re-read
  every target method from the current worktree rather than relying on a prior truncated aggregate read.

### MTA-OPS-247 — Remove an outer try when removing its finalizer

- **Observed failure:** C3 runner cleanup simplification removed an unused `finally` body but left its
  outer `try`, producing a generation-module SyntaxError during test collection. No test body,
  endpoint, runtime, or hardware action ran.
- **Cause certainty:** certain from the Python parser diagnostic at the alias following
  `_drive_simulation`.
- **Disproven alternatives:** This does not indicate a tick-runner, adapter, or Direct-stage failure;
  import failed before those paths existed.
- **Recovery and residue:** Preserve the collection error, regenerate the index, remove the redundant
  outer `try` while retaining the inner tick-failure handler, then rerun the focused tests.
- **Correction status:** runner syntax repair pending.
- **Mandatory prevention gate:** When deleting a `finally` clause, remove or replace its matching
  `try` in the same source review before executing imports or tests.

### MTA-OPS-248 — Use PowerShell-compatible regex syntax in process preflight

- **Observed failure:** C3's full-suite preflight used shell-style `--` before PowerShell's `-match`,
  so parsing failed before the pytest-process query or diff check ran. No source, process, endpoint,
  runtime, or hardware state changed.
- **Cause certainty:** certain from PowerShell's parser diagnostic identifying `--` as invalid in that
  expression.
- **Disproven alternatives:** This does not indicate an active pytest process, relay writer lock, or
  test failure; the preflight never executed.
- **Recovery and residue:** Preserve the parser error, regenerate the index, use a parenthesized
  regex expression without shell-only option syntax, then rerun the read-only preflight.
- **Correction status:** corrected preflight pending.
- **Mandatory prevention gate:** Keep shell-specific option separators out of PowerShell operators;
  validate a process-filter expression with a bounded read-only invocation before using it as a test
  launch gate.

### MTA-OPS-249 — Do not combine broad source discovery with ledger reads

- **Observed failure:** C4 entry inspection first combined a broad mixed source search, and then a
  complete current-ledger/index read. Both outputs were truncated, so neither result could support
  implementation decisions. No source, runtime, endpoint, process, or external state changed.
- **Cause certainty:** certain from the tool truncation notices. The operands exceeded the bounded
  evidence contract already established for this repository.
- **Disproven alternatives:** This is not evidence of a missing C4 entry point, an incident-ledger
  defect, or an application failure; the requested output itself was too broad to inspect.
- **Recovery and residue:** Discard both truncated results, retain the clean worktree, rebuild the
  index after recording this entry, and perform one bounded inventory or range read per invocation.
  No runtime cleanup is required.
- **Correction status:** process correction recorded before C4 source inspection resumes.
- **Mandatory prevention gate:** Never combine broad source discovery with documentation reads, and
  never read a complete ledger or index when a tail, exact search, or bounded range supplies the
  needed evidence.

### MTA-OPS-250 — Resolve planned document paths before reading phase sections

- **Observed failure:** C4 inspection guessed that the C design and prompt were under
  `docs/planning`; both operands were absent, so the planned-section search returned an error and
  yielded no document evidence. No source, runtime, endpoint, process, or external state changed.
- **Cause certainty:** certain from ripgrep's explicit missing-path diagnostics. The document names
  were known, but their repository locations had not been resolved.
- **Disproven alternatives:** The failure does not mean the C plan is absent or that C4 requirements
  changed; it only rejects the assumed parent directory.
- **Recovery and residue:** Preserve the failed lookup, regenerate the index, enumerate the exact
  filenames from the repository, then read only the returned C4 sections. No runtime cleanup is
  required.
- **Correction status:** process correction recorded before C4 source implementation.
- **Mandatory prevention gate:** Before reading any named planning document whose exact path was not
  observed in this turn, resolve its filename with a bounded `rg --files` query; never infer its
  parent directory from a conventional layout.

### MTA-OPS-251 — Enumerate package metadata before dependency inspection

- **Observed failure:** C4 dependency inspection assumed a top-level `pyproject.toml` and used a
  shell glob as a literal Windows ripgrep path. Both operands failed before any dependency evidence
  was returned. No source, runtime, endpoint, process, or external state changed.
- **Cause certainty:** certain from the missing-file and invalid-path diagnostics. This was an
  unverified layout assumption coupled with non-portable glob use.
- **Disproven alternatives:** The result does not indicate that the WebSocket dependency is absent
  or that the C4 transport cannot be implemented; no package metadata was actually read.
- **Recovery and residue:** Preserve the failed query, regenerate the index, list exact repository
  metadata filenames, then inspect one returned file per invocation. No runtime cleanup is required.
- **Correction status:** process correction recorded before selecting the CLI socket adapter.
- **Mandatory prevention gate:** Resolve package metadata with `rg --files` before opening it, and
  put any ripgrep filename filter before `--` rather than passing a shell glob as an operand.

### MTA-OPS-252 — Narrow cross-layer option searches before reading defaults

- **Observed failure:** C4 policy-default discovery searched endpoint, legacy CLI, control, and test
  layers together. The result was truncated, so it cannot establish a default or reuse contract.
  No source, runtime, endpoint, process, or external state changed.
- **Cause certainty:** certain from the truncation notice. The query crossed unrelated legacy and
  current implementation layers without a bounded target.
- **Disproven alternatives:** The truncated result does not prove a compatible default exists, nor
  does it identify a defect in Direct A/B or the new Core CLI.
- **Recovery and residue:** Discard the result, regenerate the index, and inspect the C4 driver
  policy and the specific existing CLI parser separately. No runtime cleanup is required.
- **Correction status:** process correction recorded before constructing the C4 CLI policy.
- **Mandatory prevention gate:** Search one implementation layer at a time and cap contextual output;
  do not combine legacy orchestration, endpoint policy, and tests in a single discovery query.

### MTA-QA-019 — Snapshot assertions must wait for the runner's stated checkpoint

- **Observed failure:** The C4 full suite reached `680 passed, 3 skipped` but
  `ConnectionRunServiceTests.test_one_start_idempotent_commands_pure_get_and_verified_terminal`
  observed a legitimate background transition from `preflight` to `running` between two snapshots.
  The test's runner had signalled its own `running` event, but the persisted snapshot had not yet
  reflected that phase. No endpoint, radio, process, or external state was created by C4.
- **Cause certainty:** certain from the preserved assertion diff: the only changed fields were the
  service's concurrent run phase/revision projection, not data mutated by a GET call.
- **Disproven alternatives:** This does not implicate the C4 CLI, Pair relay, Switch LDN endpoint,
  or Core cleanup; their focused tests passed before the full suite.
- **Recovery and residue:** Preserve the full-suite output, run this one test alone to distinguish
  an intermittent scheduling race from a reproducible service defect, and do not claim C4 full-suite
  green until the test has a reliable checkpoint. No runtime cleanup is required.
- **Correction status:** isolated reproduction pending.
- **Mandatory prevention gate:** Concurrent snapshot tests must wait for the persisted phase they
  compare, not merely for an event emitted before that phase is committed.

### MTA-OPS-253 — Verify Git branch, revision, and remote identity separately

- **Observed failure:** After the C4 push, one read-only shell invocation combined local HEAD,
  remote-tracking HEAD, and current-branch queries. All values agreed on `Simple-Architecture`, but
  the invocation violated the repository's one-evidence-question rule. No source, runtime, endpoint,
  process, or external state changed.
- **Cause certainty:** certain from the literal combined command. This was a procedural grouping
  error, not an ambiguous push result.
- **Disproven alternatives:** The matching hashes do not indicate a main-branch mutation or remote
  divergence; the defect is solely in evidence isolation.
- **Recovery and residue:** Preserve the successful push, regenerate the index, make the
  documentation-only correction commit, then verify final worktree cleanliness in one independent
  invocation. No runtime cleanup is required.
- **Correction status:** process correction recorded before final handoff.
- **Mandatory prevention gate:** Query current branch, local revision, remote revision, and status in
  separate shell invocations whenever each fact is used as final handoff evidence.

### MTA-OPS-254 — Protect leading-dash ripgrep patterns with the option separator

- **Observed failure:** C4 radio-gate discovery searched for a pattern beginning with `--usb-id`
  without ripgrep's option separator. Ripgrep parsed it as an unknown option and returned no source
  evidence. No source, runtime, endpoint, process, or external state changed.
- **Cause certainty:** certain from ripgrep's explicit option diagnostic. The script path was valid;
  only the pattern was parsed incorrectly.
- **Disproven alternatives:** The failed search does not indicate that the radio gate lacks USB,
  command, or execution handling.
- **Recovery and residue:** Preserve the failed query, regenerate the index, then use fixed-string
  search with `--` before the leading-dash pattern. No runtime cleanup is required.
- **Correction status:** process correction recorded before C4 identity routing is changed.
- **Mandatory prevention gate:** Any search pattern that begins with `-` must be placed after
  ripgrep's `--` option separator; do not rely on the pattern's surrounding alternation to protect it.

### MTA-QA-020 — Do not await a peer-close notification without a bounded contract

- **Observed failure:** The first C5 qualification revision called `guest.wait_generation_end()`
  immediately after `host.stop()` on a second real-relay generation. The run printed one passed test
  then remained live for three bounded waits because the test had no timeout or confirmed peer-close
  receipt. It was interrupted before any production endpoint, radio, or external resource existed.
- **Cause certainty:** certain from the test sequence and absent timeout: the assertion waited for a
  remote asynchronous event without a completion bound. This is a qualification-test race, not proof
  of a Core or cleanup defect.
- **Disproven alternatives:** The same test's first generation had already completed its relay close
  and local cleanup; no Switch hardware, real Direct stage, or production Room API was invoked.
- **Recovery and residue:** Preserve the interrupted run, regenerate the index, replace the
  unbounded peer-close wait with the existing bounded supervisor state helper, and retry only the
  C5 qualification. No runtime cleanup is required.
- **Correction status:** bounded test correction pending.
- **Mandatory prevention gate:** Every assertion that waits for an asynchronous peer transition must
  use a bounded completion signal or explicit timeout; never await an open-ended lifecycle wait in a
  qualification test.

### MTA-CORE-010 — Drain a queued generation close before stopping transport

- **Observed failure:** The bounded C5 retry proved that `host.stop()` could leave the active guest
  in `ACTIVE`: `close_generation()` queued `GENERATION_CLOSE`, then `transport.close()` immediately
  canceled the writer before the frame was necessarily sent. The guest's bounded `PAIRED` wait timed
  out. This occurred only in the real relay qualification with injected local resources.
- **Cause certainty:** certain from the supervisor order and WireClient writer ownership. A normal
  `host.close_generation()` passed because transport remained live; only the stop path canceled the
  outbound queue immediately after enqueueing the close frame.
- **Disproven alternatives:** This is not a Direct A/B, TunnelSim, relay authentication, or physical
  radio failure. The first generation's data/flags path and local cleanup had already passed.
- **Recovery and residue:** Preserve the bounded timeout, add a bounded WireClient outbound drain
  after `GENERATION_CLOSE`, and retry the C5 qualification. No external endpoint or radio was owned.
- **Correction status:** transport-drain repair pending.
- **Mandatory prevention gate:** A terminal peer-notification frame must be drained through its
  owned writer before a caller cancels that writer; test stop-driven peer closure over a real relay.

### MTA-QA-021 — Assert generation clear after terminal cleanup, not local close entry

- **Observed failure:** After adding the required outbound close drain, an existing supervisor test
  waited only for the test generation's `close()` entry event, then asserted `generation_id is None`.
  The new drain correctly kept the supervisor cleanup in progress, so the assertion observed the
  still-owned generation and failed. No endpoint, radio, or external resource was created.
- **Cause certainty:** certain from the close order: local generation close begins before terminal
  peer notification drain and only then clears the supervisor generation field.
- **Disproven alternatives:** This is not a regression in first-failure preservation, generation
  cleanup, or WireClient drain; the test observed an intermediate state as if it were terminal.
- **Recovery and residue:** Preserve the failure, regenerate the index, await the supervisor's
  terminal failure signal before asserting final generation state, then rerun focused regressions.
  No runtime cleanup is required.
- **Correction status:** terminal-signal test correction pending.
- **Mandatory prevention gate:** Tests asserting generation clear after asynchronous cleanup must
  await a terminal supervisor completion signal, never an instrumented local-resource entry event.
