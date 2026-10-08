"""Rich presentation of download data; does not call JDownloader."""

import json

from rich import box
from rich.console import Console
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import config, utils
from .stats import partition_links, summarize_transfers, transfer_progress
from .diagnostics import availability_label, diagnose_link

# Presentation order only; API request fields are defined in client.py.
LINK_DETAIL_FIELDS = (
    "uuid",
    "name",
    "packageUUID",
    "status",
    "advancedStatus",
    "running",
    "enabled",
    "finished",
    "skipped",
    "extractionStatus",
    "priority",
    "eta",
    "speed",
    "host",
    "bytesLoaded",
    "bytesTotal",
    "addedDate",
    "finishedDate",
    "comment",
    "url",
)

PACKAGE_DETAIL_FIELDS = (
    "uuid",
    "name",
    "status",
    "running",
    "enabled",
    "finished",
    "priority",
    "eta",
    "speed",
    "bytesLoaded",
    "bytesTotal",
    "saveTo",
    "childCount",
    "hosts",
    "comment",
)


def print_help(*, console=None):
    console = Console() if console is None else console

    # Header
    title = Text.assemble(
        ("JDSH ", "bold magenta"),
        (f"v{config.VERSION}", "dim white"),
    )

    # Syntax
    syntax = Text.assemble(
        ("Usage: ", "bold yellow"),
        ("jd ", "bold cyan"),
        ("[COMMAND] ", "bold green"),
        ("[ARGS]...", "dim white")
    )

    # Command Table
    table = Table(box=None, padding=(0, 2), show_header=False, expand=True)
    table.add_column("Command", style="bold cyan", width=5)
    table.add_column("Args", style="cyan", width=5)
    table.add_column("Description", style="white")

    def add_cmd(name, args, desc):
        table.add_row(Text(name), Text(args), Text(desc))
    def add_section(name):
        table.add_row(Text(f"\n{name}", style="bold yellow"))

    add_section("Dashboard")
    add_cmd("jd", "", "Launch the Interactive TUI")
    add_cmd("status", "", "Show a static snapshot of the queue")

    add_section("Queue Management")
    add_cmd("list (ls)", "[-d] [--packages] [filters/sort]", "List downloads; use jd ls --help for search, filters, and sorting")
    add_cmd("show", "<id> [--json]", "Show raw link, package, URL, and diagnosis details")
    add_cmd("why", "<id> [--json]", "Explain why a download is not progressing")
    add_cmd("check", "<id> | --all [--json]", "Force-refresh link availability")
    add_cmd("grabber", "[-d] [--json] [filters]", "Inspect LinkGrabber; use jd grabber --help for name, host, package, and job filters")
    add_cmd("add", "[<url>...] [--clipboard] [-f <path>]", "Add links to LinkGrabber (file: one URL per line)")
    add_cmd("confirm", "[<id>...] [--package <id>] | --all", "Move selected Grabber links/packages; no IDs means all pending packages")
    add_cmd("remove (rm)", "[<id>...] [--package <id>]", "Remove selected links/packages from the queue")

    add_section("Controls")
    add_cmd("enable / disable", "[<id>...] [--package <id>]", "Enable/disable selected download links or packages")
    add_cmd("resume", "[<id>...] [--package <id>]", "Request resume for selected links or packages")
    add_cmd("force", "[<id>...] [--package <id>]", "Request forced download for selected links or packages")
    add_cmd("reset", "[<id>...] [--package <id>] --yes", "Reset selected downloads (can delete files and discard progress)")
    add_cmd("priority", "<level> [<id>...] [--package <id>]", "Set selected link/package priorities")
    add_cmd("rename", "<name> --link <id> | --package <id>", "Rename one link or package")
    add_cmd("directory", "<path> --package <id>", "Change package download destination")
    add_cmd("start", "", "Start/Resume downloads")
    add_cmd("stop", "", "Stop downloads")
    add_cmd("clear", "", "Remove finished items from list")
    add_cmd("replace", "<uuid> <url>", "Replace a dead link URL")

    add_section("Utils")
    add_cmd("version", "", "Show shell and core versions")
    add_cmd("help", "", "Show this help message")

    examples = Text.from_markup(
        "[dim]# command options:[/]\n"
        "[bold cyan]jd add --help[/]\n\n"
        "[dim]# inspect queue state:[/]\n"
        "[bold cyan]jd ls[/]\n"
        "[bold cyan]jd why[/] [green]123456789[/]\n"
        "[bold cyan]jd show[/] [green]123456789[/]\n\n"
        "[dim]# force-refresh availability:[/]\n"
        "[bold cyan]jd check[/] [green]123456789[/]\n"
        "[bold cyan]jd check --all[/]"
    )

    body = Padding(table, (0, 1))

    console.print()
    console.print(Panel(
        body,
        title=title,
        border_style="#333333",
        box=box.ROUNDED,
        title_align="left"
    ))
    console.print(Padding(syntax, (1, 2)))
    console.print(Padding(examples, (0, 2)))
    console.print()


def _raw_value(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _raw_size(value):
    if value is None:
        return "null"
    return utils.human_size(value)


def _raw_detail_text(data, preferred_fields=LINK_DETAIL_FIELDS):
    if data is None:
        return Text("null")

    fields = [field for field in preferred_fields if field in data]
    fields.extend(sorted(field for field in data if field not in preferred_fields))

    detail = Text()
    for index, field in enumerate(fields):
        value = data.get(field)
        detail.append(f"{field}:", style="bold")
        if isinstance(value, (dict, list)):
            detail.append("\n")
            detail.append(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            detail.append(" ")
            detail.append(_raw_value(value))
        if index < len(fields) - 1:
            detail.append("\n")
    return detail


def _diagnosis_text(diagnosis):
    text = Text()
    text.append("state: ", style="bold")
    text.append(str(diagnosis.get("state", "UNKNOWN")))
    text.append("\nreason: ", style="bold")
    text.append(str(diagnosis.get("reason", "")))
    text.append("\nsource: ", style="bold")
    text.append(str(diagnosis.get("source", "unknown")))
    evidence = diagnosis.get("evidence")
    if evidence:
        text.append("\nevidence:\n", style="bold")
        text.append(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return text


def render_show(payload, link_id, *, console=None):
    console = Console() if console is None else console
    console.print(Panel(
        _raw_detail_text(payload["link"]),
        title=Text(f"Link: {payload['link'].get('name') or link_id}"),
        border_style="dim white",
        expand=False,
    ))

    console.print(Panel(
        _diagnosis_text(payload["diagnosis"]),
        title="Diagnosis",
        border_style="yellow",
        expand=False,
    ))

    console.print(Panel(
        _raw_detail_text(payload["package"], PACKAGE_DETAIL_FIELDS),
        title="Package",
        border_style="dim white",
        expand=False,
    ))

    console.print(Panel(
        Text(json.dumps(payload["downloadUrls"], ensure_ascii=False, indent=2, sort_keys=True)),
        title="Download URLs",
        border_style="dim white",
        expand=False,
    ))


def render_why(payload, *, console=None):
    diagnosis = payload["diagnosis"]
    console = Console() if console is None else console
    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("ID", str(payload["uuid"]))
    table.add_row("Name", Text(str(payload.get("name") or "null")))
    table.add_row("State", str(diagnosis["state"]))
    table.add_row("Availability", availability_label({"advancedStatus": payload.get("advancedStatus")}))
    table.add_row("Reason", str(diagnosis["reason"]))
    table.add_row("Source", str(diagnosis["source"]))
    table.add_row(
        "Controller",
        "UNKNOWN" if payload.get("controllerState") is None else str(payload["controllerState"]),
    )
    console.print(table)

    if diagnosis["source"] == "unknown":
        console.print(
            "[dim]JDownloader did not expose a link-level reason; "
            "the raw evidence remains available via 'jd show <id>'.[/]"
        )


def render_check(payload, *, console=None):
    status = payload.get("availableStatus") or {}
    status_id = status.get("id") or "UNKNOWN"
    label = status.get("label")
    availability = f"{status_id} ({label})" if label else status_id

    console = Console() if console is None else console
    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("ID", str(payload.get("uuid")))
    table.add_row("Name", Text(str(payload.get("name") or "null")))
    table.add_row("Availability", availability)
    console.print(table)


def render_list(links, detail=False, *, filtered=False, console=None):
    console = Console() if console is None else console
    if not links:
        render_message("No downloads match the filters." if filtered else "Download queue is empty.", console=console)
        return
    if detail:
        for link in links:
            panel = Panel(
                _raw_detail_text(link),
                title=Text(str(link['name'])),
                border_style="dim white",
                expand=False
            )
            console.print(panel)
    else:
        table = Table(box=box.SIMPLE_HEAD)
        table.add_column("ID", style="dim", no_wrap=True)
        table.add_column("State")
        table.add_column("Availability")
        table.add_column("Done/Total", justify="right")
        table.add_column("Host")
        table.add_column("Finished at", no_wrap=True)
        table.add_column("Reason")
        table.add_column("Name")

        for link in links:
            diagnosis = diagnose_link(link)
            size_fmt = f"{_raw_size(link.get('bytesLoaded'))}/{_raw_size(link.get('bytesTotal'))}"

            table.add_row(
                f"{link['uuid']}",
                str(diagnosis["state"]),
                availability_label(link),
                size_fmt,
                _raw_value(link.get("host")),
                utils.human_timestamp(link.get("finishedDate")),
                str(diagnosis["reason"]),
                Text(str(link['name'])),
            )
        console.print(table)


def render_packages(packages, *, filtered=False, console=None):
    console = Console() if console is None else console
    if not packages:
        render_message("No downloads match the filters." if filtered else "Download queue is empty.", console=console)
        return
    table = Table(title="Packages (sizes and states describe matched links)", box=box.SIMPLE_HEAD)
    for name in ("Package ID", "Name", "Links matched/total", "Done/Total",
                 "States", "Hosts", "Finished at"):
        table.add_column(name, no_wrap=name in ("Package ID", "Finished at"))
    for package in packages:
        states = ", ".join(f"{state}: {count}" for state, count in sorted(package["states"].items()))
        table.add_row(
            str(package["uuid"]) if package["uuid"] is not None else "UNKNOWN",
            Text(str(package["name"]) if package["name"] is not None else "Unknown package name"),
            f"{package['matchedCount']}/{package['linkCount']}",
            f"{_raw_size(package['bytesLoaded'])}/{_raw_size(package['bytesTotal'])}",
            states, Text(", ".join(package["hosts"]) or "UNKNOWN"),
            utils.human_timestamp(package.get("finishedDate")),
        )
    console.print(table)


def render_grabber(links, detail=False, *, filtered=False, console=None):
    console = Console() if console is None else console
    if not links:
        render_message("No LinkGrabber links match the filters." if filtered else "LinkGrabber is empty.", console=console)
        return
    table = Table(title=f"Pending Links ({len(links)})", box=box.SIMPLE)
    for label in ("ID", "Package ID", "Enabled", "Availability", "Host", "Name"):
        table.add_column(label)
    for link in links:
        enabled = link.get("enabled")
        row = [Text(str(link.get("uuid", "UNKNOWN"))), Text(str(link.get("packageUUID", "UNKNOWN"))),
               "YES" if enabled is True else "NO" if enabled is False else "UNKNOWN",
               Text(str(link.get("availability") or "NOT REPORTED")),
               Text(str(link.get("host") or "UNKNOWN")), Text(str(link.get("name") or ""))]
        table.add_row(*row)
    console.print(table)
    if detail:
        for link in links:
            console.print(Panel(Text(json.dumps(link, ensure_ascii=False, indent=2, sort_keys=True)),
                                title=Text(f"LinkGrabber link {link.get('uuid', 'UNKNOWN')}")))
    render_message("Use 'jd confirm ID' or 'jd confirm --package ID' to move specific Grabber entries. "
                   "Bare 'jd confirm' / 'jd confirm --all' moves ALL pending packages, regardless of listing filters. "
                   "Use 'jd start' to start or resume the controller; JD auto-start settings may also apply.", console=console)


def render_status(state, links, *, console=None):
    active, _ = partition_links(links)
    summary = summarize_transfers(active)

    console = Console() if console is None else console
    console.print(f"[bold]State:[/bold]  {state}")
    console.print(f"[bold]Speed:[/bold]  {utils.human_size(summary.speed)}/s")
    console.print(f"[bold]Active:[/bold] {len(active)}")

    if active:
        table = Table(box=box.SIMPLE_HEAD, show_edge=False)
        table.add_column("Name")
        table.add_column("%", justify="right")
        table.add_column("Size", justify="right")
        table.add_column("Speed", justify="right", style="cyan")
        table.add_column("ETA", justify="right", style="green")

        for l in active:
            progress = transfer_progress(l)
            size_str = f"{utils.human_size(progress.loaded)}/{utils.human_size(progress.total)}"

            table.add_row(
                Text(str(l['name'])),
                utils.human_percent(progress.percent, precision=1),
                size_str,
                f"{utils.human_size(progress.speed)}/s",
                utils.human_eta(progress.eta)
            )
        console.print(table)


def render_check_all(payload, *, console=None):
    console = Console() if console is None else console
    if payload["started"]:
        render_message(
            f"Started online status check for {payload['linkCount']} links. "
            "JDownloader will process them in the background.", console=console,
        )
    else:
        render_message("No download links to check.", console=console)


def render_message(message, *, console=None):
    """Write literal command feedback to the selected presentation output."""
    console = Console() if console is None else console
    console.print(Text(str(message)))
