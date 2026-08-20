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

from . import utils, config


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
                try:
                    return msvcrt.getch().decode("utf-8", errors="ignore")
                except:
                    pass
        return None


def generate_layout(state, running_links, enabled_unfinished_links, override_status=None):
    current_speed = sum(l.get('speed', 0) for l in running_links)
    
    total_bytes = sum(l.get('bytesTotal', 0) for l in running_links)
    loaded_bytes = sum(l.get('bytesLoaded', 0) for l in running_links)
    remaining_bytes = total_bytes - loaded_bytes
    
    # Header
    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)

    display_state = override_status if override_status else state
    
    # Colors
    if override_status:
        st_style, border_color = "bold yellow", "yellow"
    elif state in ["RUNNING", "DOWNLOADING"]:
        st_style, border_color = "bold bright_green", "green"
    elif state in ["STOPPED", "STOPPED_STATE", "IDLE"]:
        st_style, border_color = "bold red", "red"
    else:
        st_style, border_color = "bold yellow", "yellow"

    grid.add_row(
        Text.assemble("State: ", (display_state, st_style)),
        Text.assemble("Speed: ", (f"{utils.human_size(current_speed)}/s", "bold cyan")),
        f"[dim]Running total:[/dim] {utils.human_size(total_bytes)}",
    )
    grid.add_row(
        Text.assemble(
            "Running: ",
            (str(len(running_links)), "bold white"),
            "  |  Enabled unfinished: ",
            (str(len(enabled_unfinished_links)), "dim white"),
        ),
        f"[dim]Running done: [/dim] {utils.human_size(loaded_bytes)}",
        f"[dim]Running left: [/dim] [yellow]{utils.human_size(remaining_bytes)}[/]"
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
            total = link.get('bytesTotal', 1) or 1
            done = link.get('bytesLoaded', 0)
            pct = (done / total) * 100
            
            bar = ProgressBar(
                total=100, completed=pct, width=None, style="grey23", 
                complete_style="bold bright_cyan", finished_style="bold bright_green"
            )
            
            size_str = f"{utils.human_size(done)}/{utils.human_size(total)}"
            
            t_running.add_row(
                link['name'], 
                bar, 
                f"{pct:.0f}%", 
                size_str,
                f"{utils.human_size(link.get('speed', 0))}/s", 
                utils.human_eta(link.get('eta', 0))
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
                link['name'],
                "null" if status is None else str(status),
                utils.human_size(link.get('bytesTotal', 0))
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


def run(client):
    console = Console()
    console.clear()
    last_state, last_running, last_enabled_unfinished = "UNKNOWN", [], []

    try:
        with KeyboardInput() as kbd, Live(refresh_per_second=4, screen=True) as live:
            live.update(generate_layout("CONNECTING...", [], [], override_status="LOADING..."))
            
            last_state, last_running, last_enabled_unfinished = client.fetch_stats()
            live.update(generate_layout(last_state, last_running, last_enabled_unfinished))

            while True:
                start_time = time.time()
                while (time.time() - start_time) < config.REFRESH_RATE:
                    key = kbd.get_key()
                    if key == 's':
                        is_running = last_state in ["RUNNING", "DOWNLOADING"]
                        fb_status = "STOPPING..." if is_running else "STARTING..."
                        
                        live.update(generate_layout(
                            last_state,
                            last_running,
                            last_enabled_unfinished,
                            override_status=fb_status,
                        ))
                        
                        try: client.toggle_state(last_state)
                        except: pass
                        
                        break
                    
                    if key: pass 
                    time.sleep(0.1)

                state, running, enabled_unfinished = client.fetch_stats()
                last_state, last_running, last_enabled_unfinished = state, running, enabled_unfinished
                
                live.update(generate_layout(state, running, enabled_unfinished))

    except KeyboardInterrupt:
        pass
