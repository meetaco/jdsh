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
│    grabber                  [-d]                     List pending links inside LinkGrabber                                                                           │
│    add                      [<url>...] [--clipboard] [-f <path>] Add links to LinkGrabber                                                                            │
│    confirm                                           Move all pending links to Queue                                                                                 │
│    remove (rm)              <uuid>...                Remove items by ID                                                                                              │
│                                                                                                                                                                      │
│    Controls                                                                                                                                                          │
│    start                                             Start/Resume downloads                                                                                          │
│    stop                                              Pause/Stop downloads                                                                                            │
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

  # detailed list view:
  jd ls -d

  # inspect one download and related package/URL data:
  jd show 123456789
  jd show 123456789 --json
```

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
