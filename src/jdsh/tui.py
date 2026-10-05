import time
import sys
import os
from collections import deque

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
        if termios:
            if select.select([sys.stdin], [], [], 0)[0]:
                # Read bytes directly: TextIO buffering can hide the rest of an
                # escape sequence from select(). Navigation keys are ASCII.
                chunk = os.read(sys.stdin.fileno(), 64).decode("utf-8", errors="ignore")
                self.pending.extend(self.decoder.feed(chunk))
        elif msvcrt.kbhit():
            key = msvcrt.getwch()
            if self.windows_prefix:
                self.windows_prefix = False
                decoded = WINDOWS_KEYS.get(key)
                if decoded:
                    self.pending.append(decoded)
            elif key in ("\x00", "\xe0"):
                self.windows_prefix = True
            else:
                self.pending.append(key)
        return self._next_key() if self.pending else None


def generate_layout(state, running_links, enabled_unfinished_links, override_status=None,
                    *, navigation=None, height=25):
    navigation = Navigation() if navigation is None or state == "ERROR" else navigation
    navigation.sync(running_links, enabled_unfinished_links)
    body_height = max(0, height - 6)
    running_height = max(6, min(body_height - 6, body_height * 2 // 3))
    pane_heights = (running_height, max(6, body_height - running_height))
    navigation.resize([max(1, value - 5) for value in pane_heights])
    summary = summarize_transfers(running_links)

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
            (str(len(running_links)), "bold white"),
            "  |  Enabled unfinished: ",
            (str(len(enabled_unfinished_links)), "dim white"),
        ),
        f"[dim]Running done: [/dim] {utils.human_size(summary.loaded)}",
        f"[dim]Running left: [/dim] [yellow]{utils.human_size(summary.remaining)}[/]"
    )

    header = Panel(grid, title="JDownloader Panel", border_style=border_color, box=box.ROUNDED)

    # Running links
    t_running = Table(expand=True, box=box.SIMPLE, show_edge=False, pad_edge=False)
    t_running.add_column("ID", no_wrap=True)
    t_running.add_column("Name", ratio=3, no_wrap=True)
    t_running.add_column("Progress", ratio=2, no_wrap=True)
    t_running.add_column("%", width=5, justify="right", no_wrap=True)
    t_running.add_column("Size (Done/Total)", width=20, justify="right", style="dim", no_wrap=True)
    t_running.add_column("Speed", width=12, justify="right", style="cyan", no_wrap=True)
    t_running.add_column("ETA", width=10, justify="right", style="green", no_wrap=True)

    if not running_links:
        t_running.add_row("", "[dim italic]No running links[/]", "", "", "", "-", "-")
    else:
        for index, link in enumerate(navigation.visible(0), navigation.offsets[0]):
            progress = transfer_progress(link)
            bar = Text("-", justify="center") if progress.percent is None else ProgressBar(
                total=100, completed=progress.percent, width=None, style="grey23",
                complete_style="bold bright_cyan", finished_style="bold bright_green",
            )
            size_str = f"{utils.human_size(progress.loaded)}/{utils.human_size(progress.total)}"

            t_running.add_row(
                Text(str(link.get("uuid", "?"))),
                Text(' '.join(str(link['name']).splitlines())),
                bar, 
                utils.human_percent(progress.percent), 
                size_str,
                f"{utils.human_size(progress.speed)}/s", 
                utils.human_eta(progress.eta),
                style="bold reverse" if navigation.pane == 0 and index == navigation.indices[0] else None,
            )

    panel_running = Panel(t_running, title="Running Links", border_style="cyan" if navigation.pane == 0 else "white", box=box.ROUNDED)

    # Enabled unfinished links
    t_enabled = Table(expand=True, box=box.SIMPLE, show_edge=False, pad_edge=False)
    t_enabled.add_column("ID", no_wrap=True)
    t_enabled.add_column("Name", ratio=1, no_wrap=True)
    t_enabled.add_column("Status", ratio=1, style="yellow", no_wrap=True)
    t_enabled.add_column("Total Size", width=24, justify="right", style="dim", no_wrap=True)

    if not enabled_unfinished_links:
        t_enabled.add_row("", "[dim italic]No enabled unfinished links[/]", "-", "-")
    else:
        for index, link in enumerate(navigation.visible(1), navigation.offsets[1]):
            status = link.get('status')
            t_enabled.add_row(
                Text(str(link.get("uuid", "?"))),
                Text(' '.join(str(link['name']).splitlines())),
                Text("null" if status is None else " ".join(str(status).splitlines())),
                utils.human_size(link.get('bytesTotal')),
                style="bold reverse" if navigation.pane == 1 and index == navigation.indices[1] else None,
            )

    panel_enabled = Panel(t_enabled, title="Enabled Unfinished Links", border_style="cyan" if navigation.pane == 1 else "dim white", box=box.ROUNDED)

    # Footer
    pane = navigation.pane
    count = len(navigation.rows[pane])
    first = navigation.offsets[pane] + 1 if count else 0
    last = min(count, navigation.offsets[pane] + navigation.capacity[pane])
    label = "Running" if pane == 0 else "Enabled unfinished"
    footer = Align.center(Text(
        f"{label}: {first}-{last}/{count} | Selected ID: {navigation.selected_id if navigation.selected_id is not None else '-'}\n"
        "↑↓/j/k Move · Tab Pane · PgUp/PgDn Page · Home/End · s Start/Stop · ^C Quit"
    ))
    if height < 18:
        return Panel(Text("Terminal too short: use at least 18 rows. Ctrl+C quits."))
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
        with keyboard as kbd, Live(console=console, refresh_per_second=4, screen=True) as live:
            def render(snapshot, override_status):
                live.update(generate_layout(
                    snapshot.state, snapshot.running_links, snapshot.enabled_unfinished_links,
                    override_status=override_status, navigation=navigation,
                    height=console.size.height if isinstance(console.size.height, int) else 25,
                ))

            run_loop(client, get_key=kbd.get_key, render=render, clock=clock, sleep=sleep, handle_key=navigation.handle_key)
    except KeyboardInterrupt:
        pass
