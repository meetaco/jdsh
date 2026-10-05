import time
import sys
import os
import codecs
from collections import deque

msvcrt = None

try:
    # Linux & MacOS
    import select
    import tty
    import termios
except ImportError:
    # Windows
    select = tty = termios = None
    import msvcrt

from rich.live import Live
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.console import Console
from rich.align import Align
from rich.progress_bar import ProgressBar
from rich.text import Text
from rich import box

from . import tui_runtime, utils
from .tui_navigation import Navigation, KeyDecoder, WINDOWS_KEYS
from .tui_details import Details
from .tui_search import Search
from .errors import ServiceError

MIN_TERMINAL_ROWS = 18
HEADER_FOOTER_ROWS = 6
# Two panel borders, header, separator, and SIMPLE table trailing blank row.
PANEL_CHROME_ROWS = 5
from .stats import summarize_transfers, transfer_progress
# Readable compatibility aliases; patch loop constants in tui_runtime.
from .tui_runtime import (
    MIN_REFRESH_SECONDS as MIN_REFRESH_SECONDS,
    OPERATION_ERROR_SECONDS as OPERATION_ERROR_SECONDS,
    run_loop,
)


class KeyboardInput:
    def __init__(self):
        self.decoder = KeyDecoder()
        self.pending = deque()
        self.windows_prefix = False
        self.utf8 = codecs.getincrementaldecoder('utf-8')(errors='replace')

    def __enter__(self):
        if termios:
            self.old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, type, value, traceback):
        if termios:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)

    def _next_key(self):
        key = self.pending.popleft()
        if key == "\x03":
            raise KeyboardInterrupt
        return key

    def get_key(self):
        if self.pending:
            return self._next_key()
        self.pending.extend(self.decoder.expire())
        if self.pending:
            return self._next_key()
        if termios:
            try:
                readable = select.select([sys.stdin], [], [], 0)[0]
                chunk = os.read(sys.stdin.fileno(), 64) if readable else None
            except (OSError, ValueError) as error:
                raise ServiceError("Terminal input is unavailable") from error
            if chunk == b"":
                raise ServiceError("Terminal input closed")
            if chunk is not None:
                # Read bytes directly: TextIO buffering can hide the rest of an
                # escape sequence from select(). Navigation keys are ASCII.
                self.pending.extend(self.decoder.feed(self.utf8.decode(chunk)))
        elif msvcrt is not None and msvcrt.kbhit():
            key = msvcrt.getwch()
            if self.windows_prefix:
                self.windows_prefix = False
                decoded = WINDOWS_KEYS.get(key)
                if decoded:
                    self.pending.append(decoded)
                # Unknown extended keys are discarded, never replayed as commands.
            # getwch uses U+00E0 for an extended-key prefix, also the glyph à.
            # This console API cannot disambiguate those representations.
            elif key in ("\x00", "\xe0"):
                self.windows_prefix = True
            else:
                self.pending.append(key)
        return self._next_key() if self.pending else None


def _header_panel(grid, border_color, health=None, health_style=None):
    return Panel(grid, title="JDownloader Panel",
                 subtitle=Text(health, style=health_style, no_wrap=True, overflow="ellipsis") if health else None,
                 border_style=border_color, box=box.ROUNDED)


class RefreshHeader:
    """Render age on Rich's refresh thread even while the input thread is polling.

    Only read the captured snapshot/clock. Row selection and API calls remain on
    the input thread; no shared Navigation or Layout is mutated here.
    """

    def __init__(self, grid, border_color, snapshot, clock):
        self.grid, self.border_color = grid, border_color
        self.snapshot, self.clock = snapshot, clock

    def __rich_console__(self, console, options):
        health = tui_runtime.refresh_status(self.snapshot, self.clock())
        style = "green" if self.snapshot.last_success_at is not None and self.snapshot.error is None else "yellow"
        # Preserve the Layout's height when delegating; yielding a renderable
        # directly makes Rich reset height and may clip the subtitle off-screen.
        yield from console.render(_header_panel(self.grid, self.border_color, health, style), options)


def generate_layout(state, running_links, enabled_unfinished_links, override_status=None,
                    *, navigation=None, height=25, width=100, refresh_status=None,
                    refresh_snapshot=None, refresh_clock=None, details=None, search=None):
    if height < MIN_TERMINAL_ROWS:
        return Panel(Text("Terminal too short: use at least 18 rows. Ctrl+C quits."), border_style="red")
    full_running, full_unfinished = running_links, enabled_unfinished_links
    if search is not None:
        running_links = search.filter(running_links)
        enabled_unfinished_links = search.filter(enabled_unfinished_links)
    # Render transient poll failures with empty panes without changing the saved selection.
    navigation = Navigation() if navigation is None or state == "ERROR" else navigation
    navigation.sync(running_links, enabled_unfinished_links)
    body_height = max(0, height - HEADER_FOOTER_ROWS)
    running_height = max(6, min(body_height - HEADER_FOOTER_ROWS, body_height * 2 // 3))
    pane_heights = (running_height, max(6, body_height - running_height))
    navigation.resize([max(1, value - PANEL_CHROME_ROWS) for value in pane_heights])
    summary = summarize_transfers(full_running)

    # Header
    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)

    display_state = " ".join(str(override_status or state).splitlines())
    
    # Colors
    if override_status:
        st_style, border_color = "bold yellow", "yellow"
    elif state in ["RUNNING", "DOWNLOADING"]:
        st_style, border_color = "bold bright_green", "green"
    elif state in ["STOPPED", "STOPPED_STATE", "IDLE"]:
        st_style, border_color = "bold red", "red"
    else:
        st_style, border_color = "bold yellow", "yellow"

    state_text = Text.assemble("State: ", (display_state, st_style))
    state_text.no_wrap = True
    state_text.overflow = "ellipsis"
    grid.add_row(
        state_text,
        Text.assemble("Speed: ", (f"{utils.human_size(summary.speed)}/s", "bold cyan")),
        f"[dim]Running total:[/dim] {utils.human_size(summary.total)}",
    )
    grid.add_row(
        Text.assemble(
            "Running: ",
            (str(len(full_running)), "bold white"),
            "  |  Enabled unfinished: ",
            (str(len(full_unfinished)), "dim white"),
        ),
        f"[dim]Running done: [/dim] {utils.human_size(summary.loaded)}",
        f"[dim]Running left: [/dim] [yellow]{utils.human_size(summary.remaining)}[/]"
    )

    header = _header_panel(grid, border_color, refresh_status) if refresh_snapshot is None else RefreshHeader(
        grid, border_color, refresh_snapshot,
        time.monotonic if refresh_clock is None else refresh_clock,
    )

    if details is not None and details.is_open:
        polling_failed = not refresh_snapshot.is_available if refresh_snapshot is not None else state == "ERROR"
        panel = details.panel(width, body_height, polling_failed=polling_failed)
        layout = Layout()
        layout.split(Layout(header, size=4), Layout(panel, size=body_height),
                     Layout(Align.center(details.footer()), size=2))
        return layout

    # Running links: compact mode keeps the name/progress usable at 80 columns.
    compact = width < 100
    def row_id(link):
        value = str(link.get("uuid", "?"))
        return Text("..." + value[-7:] if compact and len(value) > 10 else value)

    t_running = Table(expand=True, box=box.SIMPLE, show_edge=False, pad_edge=False)
    t_running.add_column("ID", width=10 if compact else None, no_wrap=True)
    t_running.add_column("Name", ratio=3, no_wrap=True)
    t_running.add_column("Progress", ratio=2, no_wrap=True)
    t_running.add_column("%", width=5, justify="right", no_wrap=True)
    if not compact:
        t_running.add_column("Size (Done/Total)", width=20, justify="right", style="dim", no_wrap=True)
    t_running.add_column("Speed", width=10 if compact else 12, justify="right", style="cyan", no_wrap=True)
    if not compact:
        t_running.add_column("ETA", width=10, justify="right", style="green", no_wrap=True)

    if not running_links:
        t_running.add_row(*(["", "[dim italic]No running links[/]", "", "", "-"] if compact else ["", "[dim italic]No running links[/]", "", "", "", "-", "-"]))
    else:
        for index, link in enumerate(navigation.visible(0), navigation.offsets[0]):
            progress = transfer_progress(link)
            bar = Text("-", justify="center") if progress.percent is None else ProgressBar(
                total=100, completed=progress.percent, width=None, style="grey23",
                complete_style="bold bright_cyan", finished_style="bold bright_green",
            )
            size_str = f"{utils.human_size(progress.loaded)}/{utils.human_size(progress.total)}"

            row = [row_id(link), Text(' '.join(str(link['name']).splitlines())),
                   bar, utils.human_percent(progress.percent)]
            if not compact:
                row.append(size_str)
            row.append(f"{utils.human_size(progress.speed)}/s")
            if not compact:
                row.append(utils.human_eta(progress.eta))
            t_running.add_row(*row,
                style="bold reverse" if navigation.pane == 0 and index == navigation.indices[0] else None)


    running_title = "Running Links" if search is None or search.query is None else f"Running Links ({len(running_links)}/{len(full_running)} matches)"
    panel_running = Panel(t_running, title=running_title, border_style="cyan" if navigation.pane == 0 else "white", box=box.ROUNDED)

    # Enabled unfinished links
    t_enabled = Table(expand=True, box=box.SIMPLE, show_edge=False, pad_edge=False)
    t_enabled.add_column("ID", width=10 if compact else None, no_wrap=True)
    t_enabled.add_column("Name", ratio=1, no_wrap=True)
    t_enabled.add_column("Status", ratio=1, style="yellow", no_wrap=True)
    t_enabled.add_column("Total Size", width=14 if compact else 24, justify="right", style="dim", no_wrap=True)

    if not enabled_unfinished_links:
        t_enabled.add_row("", "[dim italic]No enabled unfinished links[/]", "-", "-")
    else:
        for index, link in enumerate(navigation.visible(1), navigation.offsets[1]):
            status = link.get('status')
            t_enabled.add_row(
                row_id(link),
                Text(' '.join(str(link['name']).splitlines())),
                Text("null" if status is None else " ".join(str(status).splitlines())),
                utils.human_size(link.get('bytesTotal')),
                style="bold reverse" if navigation.pane == 1 and index == navigation.indices[1] else None,
            )

    waiting_title = "Enabled Unfinished Links" if search is None or search.query is None else f"Enabled Unfinished ({len(enabled_unfinished_links)}/{len(full_unfinished)} matches)"
    panel_enabled = Panel(t_enabled, title=waiting_title, border_style="cyan" if navigation.pane == 1 else "dim white", box=box.ROUNDED)

    # Footer
    pane = navigation.pane
    count = len(navigation.rows[pane])
    first = navigation.offsets[pane] + 1 if count else 0
    last = min(count, navigation.offsets[pane] + navigation.capacity[pane])
    label = "Running" if pane == 0 else "Enabled unfinished"
    query_label = '' if search is None or search.query is None else ' | /' + search.query
    footer_text = Text(
        f"{label}: {first}-{last}/{count} | Selected ID: {navigation.selected_id if navigation.selected_id is not None else '-'}{query_label}\n"
        "j/k | Tab Pane | PgUp/Dn | Home/End | / Search | d Details | s Start/Stop | ^C",
        no_wrap=True, overflow='ellipsis',
    )
    footer = Align.center(search.prompt(width) if search is not None and search.editing else footer_text)
    layout = Layout()
    layout.split(
        Layout(header, size=4),
        Layout(panel_running, size=pane_heights[0]),
        Layout(panel_enabled, size=pane_heights[1]),
        Layout(footer, size=2)
    )
    return layout


def _poll_stats(client):
    """Compatibility helper; the loop calls tui_runtime.poll_stats directly.

    Patch tui_runtime.poll_stats to replace polling in the running dashboard.
    """
    return tui_runtime.poll_stats(client)


def run(client, *, console=None, keyboard=None, clock=None, sleep=None):
    console = Console() if console is None else console
    clock = time.monotonic if clock is None else clock
    sleep = time.sleep if sleep is None else sleep
    console.clear()

    try:
        keyboard = KeyboardInput() if keyboard is None else keyboard
        navigation = Navigation()
        details = Details(console)
        search = Search()
        last_size = [None]
        with keyboard as kbd, Live(console=console, refresh_per_second=4, screen=True) as live:
            def render(snapshot, override_status, *, refresh=False):
                size = console.size
                last_size[0] = size
                live.update(generate_layout(
                    snapshot.state, snapshot.running_links, snapshot.enabled_unfinished_links,
                    override_status=override_status, navigation=navigation,
                    height=size.height, width=size.width,
                    refresh_snapshot=snapshot, refresh_clock=clock,
                    details=details, search=search,
                ), refresh=refresh)

            def on_idle_refresh(snapshot, override_status):
                if console.size != last_size[0]:
                    render(snapshot, override_status)

            def handle_view_key(key, snapshot):
                if search.handle_key(key):
                    return True
                if key == '/' and not details.is_open:
                    search.begin()
                    return True
                if details.is_open and key == "q":
                    details.close()
                    return True
                if details.is_open and details.scroll(key):
                    return True
                if details.is_open and key == "\t":
                    return True  # Pane switching resumes after closing details.
                if key == "d":
                    # Detail reads are explicit and do not run during poll errors.
                    target = details.link_id if details.is_open else navigation.selected_id
                    if snapshot.is_available and target is not None:
                        render(snapshot, "Loading details", refresh=True)
                        details.fetch(client.device, target)
                    return True
                if details.is_open and key == "s" and snapshot.is_available:
                    details.controller_requested = True
                return False

            def handle_navigation(key):
                # Detail mode never forwards keys to the hidden queue, including
                # future navigation shortcuts. Unhandled keys retain normal sleep.
                return not details.is_open and not search.editing and navigation.handle_key(key)

            run_loop(client, get_key=kbd.get_key, render=render, clock=clock, sleep=sleep,
                     handle_key=handle_navigation, on_idle=on_idle_refresh, handle_view_key=handle_view_key)
    except KeyboardInterrupt:
        pass
