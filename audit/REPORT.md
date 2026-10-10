# Security audit report

**Target:** `meetaco/jdsh`
**Reviewed commit:** `25478ab971a8aa7ac25d79586d59c0fa95a573d9`
**Profile:** quick, source-only
**Status:** incomplete (`sandbox_controls_unavailable`)

## Results

- Confirmed vulnerabilities: 0
- Needs validation: 1
- Rejected candidates: 0
- Quick-profile source review covered the CLI, config, clipboard, output rendering, JDownloader API operations, dependencies, and release workflow.

The unresolved item is whether a remotely enabled JDownloader Local API can be reached and used without authentication by an untrusted principal. JDSH exposes download and queue operations through that endpoint, but this repository does not establish upstream authentication or deployed network exposure. See [NEEDS-VALIDATION.md](NEEDS-VALIDATION.md).

No target-controlled code was run. The audit skill requires an OS-enforced sandbox with disabled external networking, an allowlisted environment, read-only target/toolchain, scratch-only writes, and resource limits. Those controls were unavailable, so no build or tests were run and this report does not claim complete audit coverage. No live service was contacted.

The worktree had uncommitted edits in `README.md`, `src/jdsh/cli.py`, and `tests/test_cli.py`; they were excluded. This result applies only to the reviewed commit. See [FINDINGS-DETAIL.md](FINDINGS-DETAIL.md) for source review notes.
