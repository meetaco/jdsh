# 🟠 JDSH - JDownloader Shell 🔵

![preview](.github/preview-v1.0.1.webp)

Control and Manage your JDownloader within your terminal with _ease_.

Designed for Linux servers/headless environments where you need full control without a GUI; or if you just love using CLI!

Packed with various **Commands** & **Interactive Mode (TUI)**.

This tool will use your JDownloader local API, which you will need to enable manually. It uses [myjadpi](https://github.com/mmarquezs/My.Jdownloader-API-Python-Library/) package under the hood to work (kudos to the author of this package).

## Installation
```bash
pip install jdsh
```

## Setup

0.  Obviously have **JDownloader 2** installed.
1.  Enable JDownloader's Local API:
    *   Edit `<JD_FOLDER>/cfg/org.jdownloader.api.RemoteAPIConfig.json`.
    *   Set `"deprecatedapienabled": true`
    *   _(Optional)_ you may also need to set `deprecatedapilocalhostonly` to `false` if you want to access it from remote. 
    *   Restart JDownloader.

## Usage

You can now use the `jd` command globally from anywhere in your terminal.

### Interactive Mode
Use `jd --help` for the command overview and `jd <command> --help` for command-specific options (for example, `jd add --help`). Help is available without connecting to JDownloader.

Simply run `jd` without arguments to enter the interactive mode.

```bash
jd
```

*   **Tips:** 
    *   Press `s` to Start/Stop downloads. 
    *   Press `Ctrl+C` to quit.

### TUI refresh and retry feedback

The dashboard header shows `Live | Last success: Ns ago` after a successful
status refresh. The age uses elapsed time and is calculated during Rich redraws (four per
second), including while a status request is waiting for a response, without
extra API requests. `Live` means the last status poll succeeded;
it does not mean that downloads are running.

A failed poll shows `Retrying (N failures)` and the age of the last successful
refresh. Before any successful poll it says `No successful refresh yet`.
A single failure is shown as `Retrying (1 failure)`.
The counter counts consecutive failed status polls and resets on recovery;
start/stop operation failures do not affect it. JDSH retries status requests
through the existing connection at the configured refresh interval. This does
not establish a new connection or perform a download action. Failed polls keep
both panes empty and disable navigation/start/stop until status polling recovers;
the saved selection is retained for recovery.

The default clock is `time.monotonic()`, unaffected by wall-clock changes.
Suspend time may be excluded on some systems (including Linux), so the age
and poll schedule do not guarantee real elapsed time across system suspend.
Status requests remain synchronous: age redraws continue during a slow request,
but keyboard handling and new status results wait for that request to finish.

### TUI name search

From the queue, press `/` to edit a name search. Type a substring and press Enter
to apply it; Esc cancels editing and keeps the applied search. Backspace deletes
a character and Ctrl+U clears the input. Apply an empty or whitespace-only input
to clear the search and return to the full view. Search uses the same Unicode
case-insensitive substring matching as `jd ls --search`, over both existing
running and enabled-unfinished panes. It does not include disabled/finished links.

The footer shows the applied `/query`, and panel titles show matched/total rows.
Header transfer totals remain global. The active selection follows its ID if it
still matches; otherwise normal nearest-row selection applies, with no selection
for no matches. New status snapshots are filtered with the applied query, using
no additional API calls. Details use the filtered selection and remain pinned.

While editing, command letters and navigation keys do not execute queue or
controller actions. Ctrl+C still quits; Ctrl+U and backspace are available. Search
input is limited to 256 printable characters. POSIX UTF-8 input is buffered across
partial reads; a standalone Esc is recognized after the existing 150ms escape
sequence timeout. A prompt ESC+character is an ignored Alt/Meta event and does
not cancel editing or execute commands. Invalid UTF-8 bytes are discarded.
Windows getwch surrogate pairs are combined, but that API cannot distinguish the
literal character `à` from its extended-key prefix. Full Unicode input is therefore
supported on POSIX; Windows input retains this documented limitation and has only
simulated tests, not real-console validation. Multi-line pastes use their first
newline as Enter; bracketed paste mode and grapheme-cluster deletion are not
supported. Backspace deletes one Unicode code point. Search editing remains available during polling errors; pane
navigation and controller actions still require recovered status polling. Close
details with `q` before starting a search.

### TUI link details and diagnosis

Select a row and press `d` to open details for that link using the same diagnostic
service as `jd why ID`. The view shows the name, controller state, diagnosis,
reason and its source (`jdownloader`, `inferred`, or `unknown`), availability,
status and extraction state. Rich markup in server text is displayed literally, and embedded newlines are
preserved (CR/CRLF become LF). Other C0/C1 terminal control characters are
replaced with `?`.

Details are captured on demand. Press `d` again to refresh the displayed ID,
`j/k` or Up/Down to scroll, Page Up/Down or Home/End to move through long reasons,
and `q` to return to the queue. Tab switches panes after returning to the queue.
Normal status polling continues, but does not
refetch details. The details ID stays fixed even if the queue selection moves or
the link disappears; refresh then reports a missing link if it was removed.

After a status polling failure the view warns that captured details may be stale.
Scrolling and `q` remain available; `d` is ignored until status polling recovers.
Empty panes do not trigger a detail query. No availability check or per-link
operation is performed. `s` still controls the global download controller.
Detail requests are synchronous, like ordinary status requests. A loading
message is drawn before each detail request. After `s`, the details view and
footer indicate that captured controller/diagnosis information needs an explicit
`d` refresh; no extra detail query is triggered. Lowercase ASCII `d` and `q` are
the supported detail shortcuts.

### TUI navigation

Run `jd` without arguments to open the dashboard. The active pane has a cyan
border and the selected row is highlighted. Link IDs, the active pane's visible
range, and the selected ID are shown so selection remains identifiable.

| Key | Action |
| --- | --- |
| Up / Down, `k` / `j` | Move one row in the active pane |
| Tab | Switch between Running and Enabled Unfinished |
| Page Up / Page Down | Move by the active pane's visible row count |
| Home / End | Select the first / last row |
| `s` | Start/stop the global controller, as before |
| Ctrl+C | Quit and restore terminal settings |

Rows scroll within each pane instead of cutting off after the first ten waiting
links. Viewports track terminal size between polls (checked every idle input
tick); use at least 18 rows. Below 100 columns, ID cells show the final seven digits with
a `...` prefix and the running table omits size/ETA to keep names/progress readable.
The footer retains the full selected ID; shortened cell IDs are display-only.
Selection follows the link ID across refreshes, reordering, and moves between
panes. If the link disappears, the nearest remaining ordinal row is selected;
empty panes have no selected ID. A temporary poll error does not discard the
remembered selection. Each pane remembers its selected ID and scroll position
when switching.
Terminals below 18 rows show guidance without changing viewport offsets.
Standalone Esc is ignored; incomplete escape sequences expire after 150 ms.

This is single-row navigation. The dashboard still shows running links and
enabled unfinished links; finished/disabled links remain outside these views.
Navigation itself performs no API requests or mutations and does not alter the
refresh schedule. `s` controls the global controller regardless of the selected
row. Search, details, package selection and individual row actions will follow
in separate PRs. Linux/macOS ANSI keys and Windows extended keys are decoded;
Windows input is covered by simulated tests, not a live Windows terminal run.

### Commands Overview

```bash
╭─ JDSH        ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│                                                                                                                                                                      │
│    Dashboard                                                                                                                                                         │
│    jd                                                Launch the Interactive TUI                                                                                      │
│    status                                            Show a static snapshot of the queue                                                                             │
│                                                                                                                                                                      │
│    Queue Management                                                                                                                                                  │
│    list (ls)                [-d]                     List active downloads                                                                                           │
│    show                     <id> [--json]            Show raw link, package, and URL details                                                                         │
│    why                      <id> [--json]            Explain why a download is not progressing                                                                       │
│    check                    <id> | --all [--json]    Force-refresh link availability                                                                                 │
│    grabber                  [-d] [--json] [filters]               Inspect pending links; see jd grabber --help                                                       │
│    add                      [<url>...] [--clipboard] [-f <path>] Add links to LinkGrabber                                                                            │
│    confirm                  [IDs] [--package ID] | --all          Move selected entries; no IDs means all                                                            │
│    remove (rm)              [<id>...] [--package <id>]   Remove selected links/packages from queue                                                                   │
│                                                                                                                                                                      │
│    Controls                                                                                                                                                          │
│    enable / disable         [<id>...] [--package <id>]   Enable/disable selected downloads                                                                           │
│    resume                   [<id>...] [--package <id>]   Request resume for selected downloads                                                                       │
│    force                    [<id>...] [--package <id>]   Request forced download for selection                                                                       │
│    reset                    [<id>...] [--package <id>] --yes     Reset selected downloads; can delete files                                                          │
│    priority                 <level> [<id>...] [--package <id>]   Set link/package priorities                                                                         │
│    rename                   <name> --link <id> | --package <id>  Rename one link or package                                                                          │
│    directory                <path> --package <id>                Change package download destination                                                                 │
│    start                                             Start/Resume downloads                                                                                          │
│    stop                                              Stop downloads                                                                                                  │
│    clear                                             Remove finished items from list                                                                                 │
│    replace                  <uuid> <url>             Replace a dead link URL                                                                                         │
│                                                                                                                                                                      │
│    Utils                                                                                                                                                             │
│    version                                           Show shell and core versions                                                                                    │
│    help                                              Show this help message                                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

  Usage: jd [COMMAND] [ARGS]...

  # Run the interactive mode:
  jd

  # Add links, check them, then start:
  jd add "http://site.com/file.exe"
  jd add "http://site.com/archive1.zip" "http://site.com/archive2.zip"
  jd add --file urls.txt
  jd add -f "path/to/url list.txt"
  jd add --clipboard
  jd add "http://site.com/file.exe" --clipboard
  jd grabber
  jd confirm
  jd start

  # detailed list view:
  jd ls -d

  # inspect one download and related package/URL data:
  jd show 123456789
  jd show 123456789 --json
```

### Acting on selected downloads

```bash
jd disable 123456789 987654321
jd enable --package 111111111
jd resume 123456789 --package 111111111
jd force 123456789
jd rm --package 111111111
```

`enable`, `disable`, `resume`, `force`, and `remove` (alias `rm`) accept download
link IDs as positional arguments and package IDs with `--package ID`. Find link
IDs with `jd ls` and package IDs with `jd ls --packages`. Repeat `--package` for
multiple packages, or combine it with link IDs; option order does not matter.
A package selection applies to its download links. These commands operate on
the download queue, not LinkGrabber. At least one ID is required; IDs must be
positive integers within the signed 64-bit range, written with ASCII digits
`0`–`9` only. Signs, whitespace, underscores, and non-ASCII digits are rejected. Duplicate IDs are submitted
once per kind. Empty selection never means “all”.

`enable`/`disable` change the enabled state. `resume` delegates recovery/resume
behavior to JDownloader via `resumeLinks`; whether a link can resume depends
on JDownloader and the host. These commands do not explicitly start the global
controller; use `jd start` when
needed. `force` requests a forced download and may start downloads according to
JDownloader's behavior. `remove` only removes queue entries; downloaded files
are kept. Commands report submitted link/package ID counts, not affected-link
counts: a package can contain many links, selections can overlap, and missing
or stale IDs may be ignored by JDownloader. Acceptance does not guarantee that
a download can progress; inspect `jd ls` or `jd why <id>` afterward.

`--package` must be spelled in full; abbreviated options such as `--pack` are
rejected. `remove` now reports submitted link/package ID counts instead of the
old `Removed N items.` message. Scripts parsing that human-readable message
must update their handling.

`jd replace ID URL` validates the ID before any API operation, adds the new URL
with autostart, and then removes the original queue entry. If adding fails, the
original is kept. If removal fails, JDSH reports that the replacement was added
and both entries may remain; inspect `jd ls` and `jd grabber` before retrying.
The replacement is initially in LinkGrabber, so this operation does not prove
that its download will succeed.

### Inspect and confirm LinkGrabber entries

```bash
jd add "https://example.com/file.zip"     # example response: Add job ID: 123456789
jd grabber --job 123456789                # example: link 222222222, package 111111111
jd grabber --search archive --host example.com --availability online
jd grabber --package 111111111 -d
jd grabber --json
jd confirm 222222222 --package 111111111
jd confirm --all
```

`grabber` shows link and parent package IDs, enabled state, availability, host,
and name. Missing availability is shown as `NOT REPORTED`, not inferred as JD's
`UNKNOWN`. `--search` matches link names case-insensitively; `--host` matches an
exact host, case-insensitively, ignoring outer whitespace. `--availability`
accepts `ONLINE`, `OFFLINE`, `UNKNOWN`, and
`TEMP_UNKNOWN`, case-insensitively. Repeat host/availability/package/job options
to match any value within that filter; different filters intersect. A blank
search is ignored. Empty filtered output means no matches, not an empty grabber.
`-d` shows individual raw-record panels below the compact table, including URL,
size, comment, priority, status, and variants. `--json` emits only a JSON array of
queried records, includes the
same detail fields, and preserves additional fields returned by JD. These views
use LinkGrabber availability rather than download-queue diagnostic states.

`add` requests JD job association (`assignJobID: true`) and prints the server's
job ID when available. Use `grabber --job ID` to inspect that add operation;
JDSH does not guess its links from names or queue differences. Crawling is
asynchronous, so an empty result can precede link discovery; re-run the listing
later. Older servers may omit the job ID; JDSH reports that no usable job ID
was returned.
Use the other listing filters then.
No automatic polling, confirmation, or starting is added.

`confirm` accepts LinkGrabber link IDs and repeatable `--package ID`, including
mixed selections. `confirm` does not support job selection: positional IDs
are interpreted as LinkGrabber link IDs, never job IDs. Use the link/package
IDs shown by `grabber`. For `--package 3 1`, only `3` is the package ID; `1` is a
positional link ID. Repeat `--package` to select more packages. IDs use the
same strict ASCII positive signed-64-bit format
as download actions, and duplicates are submitted once per namespace. A package
selection includes its children, including ones hidden by listing filters.
LinkGrabber IDs belong to pending entries; use `jd grabber` rather than `jd ls` to find them.
For compatibility, **bare `jd confirm` still moves all pending packages**;
`--all` expresses that scope explicitly and cannot be combined with IDs.
**Listing filters never limit a later confirm command.** In shell scripts, avoid
`jd confirm $IDS` without first checking that `$IDS` is nonempty: an empty
expansion invokes the legacy all-package operation.

Confirmation submits one move request without retry and reports submitted ID
counts, not completed moves or affected links. Missing/stale IDs may be ignored
upstream. The all-package operation first snapshots package IDs (including
packages hidden by listing filters); packages arriving afterward require another
confirmation. JDSH does not explicitly start the controller, but JD auto-start
settings can apply when links enter the queue. Inspect `jd ls` afterward and use
`jd start` when needed. Human-readable confirm output now says `Submitted`
instead of claiming the move has finished; scripts parsing it must update.

### Reset, rename, priority, and destination

```bash
jd reset 123456789 --yes
jd reset --package 111111111 --yes
jd priority high 123456789 --package 111111111
jd rename "new name.zip" --link 123456789
jd rename "New package" --package 111111111
jd directory "/downloads/new folder" --package 111111111
```

`reset` shares the positional link IDs and repeatable `--package ID` selection
used by the other download actions. It resets state/progress through JDownloader
and can delete existing files, including completed downloads; `--yes` is required
to acknowledge that behavior. It does not explicitly start the global controller.
Use `resume` for a resume/recovery request instead of discarding progress.

`priority LEVEL` accepts `HIGHEST`, `HIGHER`, `HIGH`, `DEFAULT`, `LOW`, `LOWER`,
and `LOWEST` (case-insensitive), followed by link IDs and/or `--package ID`.
It sets the selected link priorities and/or selected package priorities.

`rename NAME` requires exactly one `--link ID` or `--package ID`. Repeating a
target option in the CLI is rejected; direct service callers deduplicate IDs
before requiring one unique target. Link names must be file names without path
separators;
package names are display labels and can contain separators or be `.` / `..`.
Neither name can be blank or contain Unicode category `Cc` control characters
(including newlines, tabs, and NEL). Other Unicode categories, including format
characters (`Cf`) and line/paragraph separators (`Zl`/`Zp`), are preserved.
Values are passed unchanged, including spaces and Unicode. A name
starting with `-` can be supplied after `--` (for example,
`jd rename --link 123456789 -- "-name.zip"`). JDownloader can rename an existing
downloaded file when renaming a link; this request is not limited to display text.

`directory PATH` requires one or more `--package ID` options; it does not accept
link IDs or infer their parent packages. Supply an absolute POSIX or Windows
path on the **JDownloader machine**. JDSH passes it unchanged and does not expand
`~`, environment variables, or check/create folders on the client. Quote paths
containing spaces, and Windows paths when running in a POSIX shell. JDownloader
controls when the destination change is applied and may move existing files.
Root paths such as `/` and `C:\` are allowed as absolute destinations.
Path existence and permissions are determined on the JDownloader machine.

These commands validate values before connecting and submit one request without
retrying. Messages show submitted target counts; acceptance does not prove the
asynchronous changes have completed. Missing/stale IDs can be ignored upstream.
Inspect `jd ls -d` or `jd show ID` afterward to confirm the resulting state.

### Browsing the download queue

```bash
jd ls --search archive
jd ls --state waiting --host example.com
jd ls --state running --state waiting --sort name
jd ls --sort size --reverse
jd ls -d --search archive
jd ls --packages
jd ls --packages --search archive --state waiting --sort progress --reverse
```

`list` and `ls` accept the same options. `--search` matches a case-insensitive
substring of a link's name (blank or whitespace-only search is ignored); with
`--packages` it also matches package names.
`--host` matches an exact host name, ignoring case; blank or whitespace-only
host values are rejected. Repeat `--state` or `--host`
to match any of the supplied values. Different filters are combined with AND.
State names are the same diagnostic states shown by `jd ls` and `jd why`:
`RUNNING`, `FINISHED`, `DISABLED`, `PROCESSING`, `WAITING`, `SKIPPED`, `FINAL`,
`OFFLINE`, `STATUS`, and `UNKNOWN`; lowercase input is accepted. `WAITING` can
include enabled idle links whose precise reason is unknown.

`--sort` accepts `name`, `id`, `host`, `size` (total bytes), or `progress`
(completed percentage). Sorting is ascending unless `--reverse` is supplied;
`--reverse` requires `--sort`. Unknown values remain last in either direction,
and equal values retain their original order. Unknown or zero total sizes give
an unknown completion percentage. With no sorting option, the API order is kept.

`--packages` displays package IDs and names, matched/total link counts, matched
bytes downloaded/total bytes, diagnostic state counts, and hosts. Filters apply
before aggregation: the sizes, states, hosts, and sorting keys describe only the
matched links, while the total link count comes from the full link snapshot.
A package with any unknown member size has an unknown aggregate size (`null`).
Hosts are deduplicated and ordered ignoring case; the first API spelling is
kept. Packages with no matching links are omitted, as are empty packages. Links with
missing package IDs appear in an `UNKNOWN` ID group (search can match their link
names, but there is no package name to search); missing package metadata
keeps the actual ID and displays `Unknown package name`. Package metadata and
links are separate API reads, so names may be unavailable if the queue changes
between them. `--packages` cannot be combined with `-d`/`--detail`; use detailed
link output to inspect the raw fields.

`jd confirm` moves **all** pending LinkGrabber packages to the download queue. It does not explicitly start the download controller; use `jd start` to start or resume it. If the controller is already running, newly moved links may begin downloading.

`jd show <id>` uses the numeric download-link ID shown by `jd ls`. It reports the raw download-link state, the parent package details when available, and separate `getDownloadUrls` responses for all five JDownloader URL display types: `CUSTOM`, `REFERRER`, `ORIGIN`, `CONTAINER`, and `CONTENT`. JDownloader selects only the first matching URL type within a single `getDownloadUrls` request, so JDSH queries each type separately. `--json` emits one object with `link`, `package`, and `downloadUrls`; the keys under `downloadUrls` are the requested URL types. If JDownloader's optional `UseUrlOrderForMyJD` setting is enabled, JDownloader may override the requested type with its configured URL order. The download-link password field is intentionally not requested by this diagnostic command.

On macOS, `jd add --clipboard` reads the clipboard's `public.html` representation first. If the HTML contains links, JDSH adds the targets from each `<a href="...">` rather than the displayed text. If HTML is unavailable or contains no links, it falls back to the clipboard's plain-text contents. A failure to read the HTML representation is reported as an error instead of silently treating displayed text as a link target.

`jd add --file <path>` (or `-f <path>`) reads a UTF-8 text file containing one URL per line, with or without a BOM. Blank lines are ignored and surrounding whitespace is trimmed. You can combine it with positional URLs and `--clipboard`; links are added in that order, keeping only the first occurrence of each URL. An unreadable file or an input containing no URLs produces an error without adding links.

## Transfer display

CLI and TUI use the same size, speed and progress calculations. Unknown values
(missing, null or negative API sentinel values) are displayed as `null`; a known
zero size remains `0 B`. A percentage that cannot be calculated is shown as `-`,
including zero-byte totals. Rounding keeps incomplete transfers below 100% at the selected display precision.
Displayed percentages are capped at 100%, while raw
loaded/total values remain available in detailed and JSON output.

Running totals are unknown when any selected running link has an unknown value
for that field; they do not silently show partial totals. An empty running
selection has zero totals. Remaining bytes are calculated per link before
summing so one link's excess loaded bytes cannot cancel another link's remaining
bytes. The loaded sum retains raw counts, so it can exceed the total when the
API reports an overrun; loaded + remaining need not equal total. Zero or unknown
ETA retains the existing `-` display (the zero-preservation rule applies to
sizes and speeds). Finished links are excluded from running/enabled-unfinished summaries.

## Errors

Command failures are written to stderr and exit with status 1; argument errors
exit with status 2. Diagnostic JSON is written only on success. The TUI shows
polling/operation failures and keeps polling so it can recover. If `replace`
removes the original link but cannot add its replacement, it reports that partial
result and asks you to add the replacement URL again.
Set `JDSH_DEBUG=1` to include JDSH tracebacks on stderr when diagnosing failures
(for example, `JDSH_DEBUG=1 jd status`). JSON output still goes only to stdout.
TUI polling and control diagnostics now use the `jdsh.tui_runtime` logger.
If you configure a filter specifically for `jdsh.tui`, update it to
`jdsh.tui_runtime` or the parent `jdsh` logger.
TUI operation errors remain visible for five seconds, or until the next successful
operation; long messages are shown on one line with an ellipsis.

## Config
By default, the application runs with standard settings (`Host: 127.0.0.1, Port: 3128`). You can override these defaults by creating a configuration file.

Create file at `~/.config/jdsh/jdsh.conf`, with the contents below.
You may uncomment any line and change when you need.

`jdsh.conf` is preferred. The previously documented `jdsh.config` filename is
also supported when `jdsh.conf` is absent; the two files are not merged. Missing
files use defaults, while unreadable or invalid files report an error. Existing
files must contain a `[settings]` section; empty files and misspelled sections are
errors. An empty `[settings]` section uses defaults and still takes precedence
over `jdsh.config`. Settings are loaded at startup rather than import time. `HOST` must be nonempty, `PORT`
must be between 1 and 65535, and `REFRESH_RATE` must be finite and positive. TUI polling has a minimum interval of 0.1
seconds.
`jd help` remains available even if settings are invalid.

```ini
[settings]
# HOST = 127.0.0.1
# PORT = 3128

# update interval of interactive mode, in seconds
# REFRESH_RATE = 1.0
```

---
#### Enjoying the tool? Your supports would keep me at it! 💖

[![Donate with Bitcoin](https://img.shields.io/badge/Donate-Bitcoin-orange.svg?logo=bitcoin)](https://blockchain.com/btc/address/bc1qvmv8cnfd0hfc82rm3r9zzq6uheejgw5hfzn426)
[![Donate with Ethereum](https://img.shields.io/badge/Donate-Ethereum-silver.svg?logo=ethereum)](https://etherscan.io/address/0xA25c8eF121ba010d09c6A7E1228be7da523933f8)
[![Donate with Tehter (BEP20)](https://img.shields.io/badge/Donate-Tether%20(BEP20)-blue.svg?logo=tether)](https://bscscan.com/address/0x283857017efb4B1F9fAe57F4599C20FD5bCE1871)
