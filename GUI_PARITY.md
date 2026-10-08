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
| Downloads | Explain idle/waiting link | ✅ | ✅ | `jd why <id>` distinguishes JD-provided, inferred and unknown reasons. |
| Downloads | Availability re-check | ✅ | ❌ | `jd check <id>` / `jd check --all`. |
| Downloads | Start / stop controller | ✅ | ✅ | Existing controls. |
| Downloads | Enable / disable selection | ✅ | ❌ | `jd enable` / `jd disable`, link IDs and `--package`. |
| Downloads | Force download | ✅ | ❌ | `jd force`, link IDs and `--package`. |
| Downloads | Resume / reset / unskip | 🟡 | ❌ | `jd resume` and `jd reset --yes` available; unskip remains pending. |
| Downloads | Rename link / package | ✅ | ❌ | `jd rename NAME --link ID` or `--package ID`. |
| Downloads | Priority | ✅ | ❌ | `jd priority LEVEL`, with explicit link/package selection. |
| Downloads | Download directory | ✅ | ❌ | `jd directory PATH --package ID`; path is on the JD machine. |
| Downloads | Move / reorder links and packages | ❌ | ❌ | Exposed by downloadsV2. |
| Downloads | Stop mark | ❌ | ❌ | Exposed by downloadsV2. |
| Downloads | Comments | 🟡 | ❌ | Readable in detailed output; mutation not exposed. |
| LinkGrabber | List links | ✅ | ❌ | Existing `jd grabber`. |
| LinkGrabber | Add / confirm links | ✅ | ❌ | `jd add` prints server job ID; `jd confirm ID` / `--package ID`; bare confirm remains all. |
| LinkGrabber | Inspect full state | 🟡 | ❌ | `jd grabber` state, host/name/availability/package/job filters, `-d` / `--json`; dedicated package view remains pending. |
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
| TUI | Select links / packages | ❌ | 🟡 | Link-row selection, scrolling and pane switching available; package/multiple selection remains pending. |
| TUI | Link details / diagnosis pane | ❌ | ✅ | d opens read-only selected-link diagnosis using the CLI service; q returns. |

## Implementation phases

### Phase 1 — observability

- [x] Preserve raw JDownloader state in detailed output.
- [x] Force-refresh availability for one link or the whole queue.
- [x] Add a conservative diagnostic model with explicit provenance.
- [x] Surface state, availability and reason in the default list.
- [x] Add `jd why <id>`.
- [x] Add package-oriented queue view and filters/sorting (`jd ls --packages`, `--search`, `--state`, `--host`, `--sort`, including `finished` for completion-time order).
- [x] Display JD2 completion timestamps in link/package list columns with local time and UTC offset.
- [x] Improve TUI state/diagnosis visibility with on-demand selected-link details.

### Phase 2 — download actions

Expose existing downloadsV2 operations with consistent link/package selection:
enable/disable, force, resume, reset, unskip, rename, priority, destination,
move/reorder, stop mark and comments.

Enable/disable, resume, force, and queue removal now share explicit link/package
selection. `unskip` remains pending investigation: the public API documentation
and interface advertise package IDs before link IDs, while the published
implementation treats the first array as link IDs. Resolve compatibility before
exposing this operation, to avoid applying it to the wrong selection. Reset (with
explicit acknowledgement), rename, priority, and destination are also available.
Move/reorder, stop marks, and comments remain pending.

### Phase 3 — LinkGrabber

Bring LinkGrabber inspection and actions to roughly the same level as Downloads,
including variants where the upstream API supports them. CLI inspection now
shows raw LinkGrabber state and supports filters plus selective confirmation.
`jd add` requests job association and exposes the returned ID for `grabber --job`.
Dedicated package summaries and LinkGrabber editing actions remain pending.

### Phase 4 — accounts, extraction and settings

Make routine headless administration possible without opening the GUI. Treat
credentials as write-only wherever practical and never print them by default or
in diagnostic JSON.

### Phase 5 — TUI

Build the TUI on the same command/service layer rather than reimplementing
JDownloader behavior. Row navigation now supports Up/Down, j/k, Tab, Page
Up/Down and Home/End with ID-preserving selection and height-based viewports.
The header now shows last successful refresh age and consecutive failed status
polls, with retry feedback and recovery through the existing connection.
Selected-link details/diagnosis now use the same service as jd why, with explicit
refresh and scrollable text. Local name search is also available via / with
Unicode matching and no extra status queries. Package hierarchy and action
shortcuts remain pending and should use the underlying CLI operations.

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

## Usability delivery order

Deliver these as separate reviewable PRs, using shared CLI services for later TUI work:

1. Command-specific offline help and accurate add/confirm/start guidance.
   Keep configuration documentation aligned with the existing `jdsh.conf` and
   legacy `jdsh.config` support.
2. Queue search, state/host filters, sorting, and package summaries.
3. Consistent link/package selection and individual download actions.
4. LinkGrabber inspection and selective confirmation, including identifying the
   links from a particular add operation.
5. TUI selection, scrolling, search, details/diagnosis, and discoverable shortcuts.
   Show last successful refresh and reconnection state during connection failures.
6. Connection/configuration diagnosis (`jd doctor`) and consistent JSON output
   for list, status, and LinkGrabber commands.

Replacement already adds the new URL before removing the original link. Further
replacement improvements should preserve that ordering and make partial outcomes
clear to the user. Account, extraction, and settings controls remain in the GUI
parity phases above.
