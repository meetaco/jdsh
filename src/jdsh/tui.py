import time
import sys

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
from .stats import summarize_transfers, transfer_progress
# Readable compatibility aliases; patch loop constants in tui_runtime.
from .tui_runtime import (
    MIN_REFRESH_SECONDS as MIN_REFRESH_SECONDS,
    OPERATION_ERROR_SECONDS as OPERATION_ERROR_SECONDS,
    run_loop,
)


class KeyboardInput:
    def __enter__(self):
        if termios:
            self.old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, type, value, traceback):
        if termios:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)

    def get_key(self):
        if termios:
            if select.select([sys.stdin], [], [], 0)[0]:
                return sys.stdin.read(1)
        
        elif msvcrt:
            if msvcrt.kbhit():
                return msvcrt.getch().decode("utf-8", errors="ignore")
        return None


def generate_layout(state, running_links, enabled_unfinished_links, override_status=None):
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
    t_running.add_column("Name", ratio=3, no_wrap=True)
    t_running.add_column("Progress", ratio=2) 
    t_running.add_column("%", width=5, justify="right")
    t_running.add_column("Size (Done/Total)", width=20, justify="right", style="dim")
    t_running.add_column("Speed", width=12, justify="right", style="cyan")
    t_running.add_column("ETA", width=10, justify="right", style="green")

    if not running_links:
        t_running.add_row("[dim italic]No running links[/]", "", "", "", "-", "-")
    else:
        for link in running_links:
            progress = transfer_progress(link)
            bar = Text("-", justify="center") if progress.percent is None else ProgressBar(
                total=100, completed=progress.percent, width=None, style="grey23",
                complete_style="bold bright_cyan", finished_style="bold bright_green",
            )
            size_str = f"{utils.human_size(progress.loaded)}/{utils.human_size(progress.total)}"

            t_running.add_row(
                Text(str(link['name'])),
                bar, 
                utils.human_percent(progress.percent), 
                size_str,
                f"{utils.human_size(progress.speed)}/s", 
                utils.human_eta(progress.eta)
            )

    panel_running = Panel(t_running, title="Running Links", border_style="white", box=box.ROUNDED)

    # Enabled unfinished links
    t_enabled = Table(expand=True, box=box.SIMPLE, show_edge=False, pad_edge=False)
    t_enabled.add_column("Name", ratio=1, no_wrap=True)
    t_enabled.add_column("Status", ratio=1, style="yellow")
    t_enabled.add_column("Total Size", width=24, justify="right", style="dim")

    if not enabled_unfinished_links:
        t_enabled.add_row("[dim italic]No enabled unfinished links[/]", "-", "-")
    else:
        limit = 10
        for link in enabled_unfinished_links[:limit]:
            status = link.get('status')
            t_enabled.add_row(
                Text(str(link['name'])),
                "null" if status is None else str(status),
                utils.human_size(link.get('bytesTotal'))
            )
        if len(enabled_unfinished_links) > limit:
            t_enabled.add_row(f"[italic]...and {len(enabled_unfinished_links)-limit} more[/]", "", "")

    panel_enabled = Panel(t_enabled, title="Enabled Unfinished Links", border_style="dim white", box=box.ROUNDED)

    # Footer
    footer = Align.center("[dim]Press [bold white]s[/] to Start/Stop  |  [bold white]Ctrl+C[/] to Quit[/]")

    layout = Layout()
    layout.split(
        Layout(header, size=4),
        Layout(panel_running, ratio=2),
        Layout(panel_enabled, ratio=1),
        Layout(footer, size=1)
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
        with keyboard as kbd, Live(console=console, refresh_per_second=4, screen=True) as live:
            def render(snapshot, override_status):
                live.update(generate_layout(
                    snapshot.state, snapshot.running_links, snapshot.enabled_unfinished_links,
                    override_status=override_status,
                ))

            run_loop(client, get_key=kbd.get_key, render=render, clock=clock, sleep=sleep)
    except KeyboardInterrupt:
        pass
