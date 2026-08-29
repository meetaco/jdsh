# JDownloader GUI parity roadmap

JDSH aims to make the information and day-to-day controls available in the
JDownloader 2 GUI accessible from a headless CLI/TUI workflow as well.

This document tracks user-visible parity rather than raw API coverage. A feature
is only marked complete when it is practical to discover and use from JDSH.

Legend:

- ✅ usable from JDSH
- 🟡 partially available / missing important UX
- ❌ not exposed yet
- ⚪ needs upstream/API investigation

| Area | GUI capability | CLI | TUI | Notes / next work |
| --- | --- | :---: | :---: | --- |
| Downloads | Queue listing | ✅ | 🟡 | CLI now shows state, availability, host and reason; TUI remains limited. |
| Downloads | Raw link details | ✅ | ❌ | `jd ls -d`, `jd show <id>`. |
| Downloads | Explain idle/waiting link | ✅ | ❌ | `jd why <id>` distinguishes JD-provided, inferred and unknown reasons. |
| Downloads | Availability re-check | ✅ | ❌ | `jd check <id>` / `jd check --all`. |
| Downloads | Start / stop controller | ✅ | ✅ | Existing controls. |
| Downloads | Enable / disable selection | ❌ | ❌ | downloadsV2 `setEnabled`. |
| Downloads | Force download | ❌ | ❌ | downloadsV2/downloadcontroller force endpoint. |
| Downloads | Resume / reset / unskip | ❌ | ❌ | Exposed by downloadsV2. |
| Downloads | Rename link / package | ❌ | ❌ | Exposed by downloadsV2. |
| Downloads | Priority | ❌ | ❌ | Exposed by downloadsV2. |
| Downloads | Download directory | 🟡 | ❌ | Visible via package details; mutation not exposed. |
| Downloads | Move / reorder links and packages | ❌ | ❌ | Exposed by downloadsV2. |
| Downloads | Stop mark | ❌ | ❌ | Exposed by downloadsV2. |
| Downloads | Comments | 🟡 | ❌ | Readable in detailed output; mutation not exposed. |
| LinkGrabber | List links | ✅ | ❌ | Existing `jd grabber`. |
| LinkGrabber | Add / confirm links | ✅ | ❌ | Existing `jd add`, `jd confirm`. |
| LinkGrabber | Inspect full state | ❌ | ❌ | Bring to parity with Downloads. |
| LinkGrabber | Enable / disable / priority | ❌ | ❌ | Implement after Downloads actions. |
| LinkGrabber | Rename / move / destination | ❌ | ❌ | Implement after Downloads actions. |
| LinkGrabber | Variants | ❌ | ❌ | Needs command design. |
| Accounts | List accounts / status | ❌ | ❌ | accountsV2 API available. |
| Accounts | Refresh accounts | ❌ | ❌ | accountsV2 API available. |
| Accounts | Enable / disable accounts | ❌ | ❌ | accountsV2 API available. |
| Accounts | Add / remove accounts | ❌ | ❌ | Must avoid leaking credentials in output/history. |
| Extraction | Queue / archive status | ❌ | ❌ | extraction API available. |
| Extraction | Start / cancel extraction | ❌ | ❌ | extraction API available. |
| Extraction | Archive settings | ❌ | ❌ | extraction API available. |
| Settings | Speed limit / pause | 🟡 | ❌ | Controller controls exist; ergonomic config commands missing. |
| Settings | Max simultaneous downloads | ❌ | ❌ | Add human-friendly config wrapper. |
| Settings | Per-host / chunk limits | ❌ | ❌ | Add human-friendly config wrapper. |
| Captcha | See pending captcha | ⚪ | ❌ | Investigate local API surface and headless flow. |
| Captcha | Submit captcha response | ⚪ | ❌ | Investigate local API surface and 2Captcha interaction. |
| Reconnect | State / trigger reconnect | ⚪ | ❌ | Investigate API and GUI behavior. |
| TUI | Select links / packages | ❌ | ❌ | Needed before action parity can be useful in TUI. |
| TUI | Link details / diagnosis pane | ❌ | ❌ | Build on the CLI diagnostics model. |

## Implementation phases

### Phase 1 — observability

- [x] Preserve raw JDownloader state in detailed output.
- [x] Force-refresh availability for one link or the whole queue.
- [x] Add a conservative diagnostic model with explicit provenance.
- [x] Surface state, availability and reason in the default list.
- [x] Add `jd why <id>`.
- [ ] Add package-oriented queue view and filters/sorting.
- [ ] Improve TUI state/diagnosis visibility.

### Phase 2 — download actions

Expose existing downloadsV2 operations with consistent link/package selection:
enable/disable, force, resume, reset, unskip, rename, priority, destination,
move/reorder, stop mark and comments.

### Phase 3 — LinkGrabber

Bring LinkGrabber inspection and actions to roughly the same level as Downloads,
including variants where the upstream API supports them.

### Phase 4 — accounts, extraction and settings

Make routine headless administration possible without opening the GUI. Treat
credentials as write-only wherever practical and never print them by default or
in diagnostic JSON.

### Phase 5 — TUI

Build the TUI on the same command/service layer rather than reimplementing
JDownloader behavior. Add selection, package hierarchy, details/diagnosis and
action shortcuts only after the underlying CLI operations are complete.

## Diagnostic policy

JDownloader does not always expose one canonical reason for an idle link. JDSH
must not turn absence of evidence into a fabricated explanation such as
"waiting for global slot".

Every diagnosis therefore includes a `source`:

- `jdownloader`: directly backed by a returned JD link/controller state.
- `inferred`: a conservative conclusion from multiple returned states.
- `unknown`: JD exposes no link-level reason that explains the current wait.

Raw state remains available through `jd show <id>` and `jd ls -d` so a diagnosis
can always be audited.
