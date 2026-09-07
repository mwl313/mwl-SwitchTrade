# CI #104 / #112 state read failure

Original evidence:
[run #104](https://github.com/mwl313/mwl-SwitchTrade/actions/runs/33962134341)
at `63216cf05908467dcb44665c9d744cf6db46bd21` and
[run #112](https://github.com/mwl313/mwl-SwitchTrade/actions/runs/34094493903)
at `f24eb8c94410491db842dbd64ed0e410a71cccf5`.

Both Windows failures are the same test:
`DistributedContractTests.test_explicit_file_checkpoint_keeps_member_alive_without_stdin`.
The polling caller failed inside `DistributedControl.read_state` ->
`Path.read_text` -> `io.open`, with `PermissionError: [Errno 13]` against its own
temporary `distributed-control-state.json`. The validator wrapped it as
`DISTRIBUTED_CONTROL_STATE_INVALID`. #104: 1 failed/695 passed/3 skipped.
#112: 1 failed/728 passed/3 skipped. Actual LDN integration tests passed #112.

This was **not** a failed JSON assertion, a bad identity, or a writer's
`os.replace` traceback. Existing Windows writer retries did not cover a reader
opening the destination during publication. The test concurrently publishes
the awaiting-user state and polls it. A Windows destination-access window is
consistent with both reproductions; the logs do not expose a Win32 error code
or prove whether antivirus participated. No antivirus/ACL bypass is justified.

The correction is limited to a read of that exact published control-state
filename on Windows: retry PermissionError for at most 250ms, retaining the
first denial as the final exception cause. It never retries an operation,
command submission, parse failure, missing file, invalid identity or schema.
Persistent denial still fails closed. State authority/checkpoints are unchanged
and remain outside the new Core CLI path.

`tests/test_control_state_windows_access.py` verifies transient and permanent
reader denial, original-cause preservation, no command creation, no retries for
bad JSON/missing files, and 100 real atomic publications concurrent with strict
identity/sequence reads. `tests/test_distributed_harness.py` includes the exact
original failed test. Combined focused result: 35 passed.

This diagnosis is not a final-SHA CI closure. Final Windows/Ubuntu results must
be recorded separately after all software changes are complete.
