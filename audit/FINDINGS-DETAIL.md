# Findings detail

No confirmed vulnerability was demonstrated in committed source.

## Source review notes

- The default API target is loopback (`src/jdsh/config.py:18-19`), while README documents remote Local API setup (`README.md:20-25`). JDownloader project manager guidance states the deprecated Local API has no authentication or encryption by default ([source](https://board.jdownloader.org/showthread.php?p=547625)). JDSH has no app-layer authentication in the connection path (`src/jdsh/client.py:111-125`). The remaining unknown is whether deployment network controls expose it to lower-trust principals; tracked as needs validation.
- Link detail queries intentionally omit the download password (`src/jdsh/client.py:28-38`). Explicit diagnostic commands can still print URLs and package paths (`src/jdsh/cli.py:253-327`); this is same-user, user-invoked output.
- macOS clipboard input is parsed as hrefs or whitespace-delimited text and passed to LinkGrabber without autostart (`src/jdsh/clipboard.py:44-60,120-137`; `src/jdsh/cli.py:593-611`). No shell execution path was found; clipboard subprocess calls use fixed argv and a timeout (`src/jdsh/clipboard.py:63-95`).
- API-provided strings reach Rich rendering, and large responses are rendered locally (`src/jdsh/cli.py`, `src/jdsh/tui.py`). The critic identified these as bounded follow-up review areas; no demonstrated terminal attack or shared-resource boundary violation was established.
- Release actions use version tags, dependencies are not pinned, and the release workflow does not run tests (`.github/workflows/release.yaml:17-26`, `pyproject.toml:1-17`). These are hardening recommendations without a demonstrated exploit path.
- At audited commit `25478ab`, README named `jdsh.config` while source read `jdsh.conf` (`README.md:95-108`, `src/jdsh/config.py:13-20`). This was subsequently fixed on `main`, which now prefers `jdsh.conf` and supports `jdsh.config` as an alias.

No target source was modified.
