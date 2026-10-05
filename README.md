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
│    grabber                  [-d]                     List pending links inside LinkGrabber                                                                           │
│    add                      [<url>...] [--clipboard] [-f <path>] Add links to LinkGrabber                                                                            │
│    confirm                                           Move all pending links to Queue                                                                                 │
│    remove (rm)              [<id>...] [--package <id>]   Remove selected links/packages from queue                                                                   │
│                                                                                                                                                                      │
│    Controls                                                                                                                                                          │
│    enable / disable         [<id>...] [--package <id>]   Enable/disable selected downloads                                                                           │
│    resume                   [<id>...] [--package <id>]   Request resume for selected downloads                                                                       │
│    force                    [<id>...] [--package <id>]   Request forced download for selection                                                                       │
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
positive integers within the signed 64-bit range. Duplicate IDs are submitted
once per kind. Empty selection never means “all”.

`enable`/`disable` change the enabled state. `resume` delegates recovery/resume
behavior to JDownloader via `resumeLinks`; whether a link can resume depends
on JDownloader and the host. These commands do not explicitly start the global controller; use `jd start` when
needed. `force` requests a forced download and may start downloads according to
JDownloader's behavior. `remove` only removes queue entries; downloaded files
are kept. Commands report submitted link/package ID counts, not affected-link
counts: a package can contain many links, selections can overlap, and missing
or stale IDs may be ignored by JDownloader. Acceptance does not guarantee that
a download can progress; inspect `jd ls` or `jd why <id>` afterward.

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
