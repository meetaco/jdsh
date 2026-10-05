"""Command definitions and argument validation, independent of CLI execution."""

import argparse
from typing import Sequence

from .grabber_view import AVAILABILITIES
from .queue_options import LINK_STATES, SORT_KEYS
from .download_selection import SELECTION_OPTION_COMMANDS, download_id
from .download_values import nonblank_text, priority_value, rename_value, directory_value


class _SingleTarget(argparse.Action):
    def __call__(self, parser, namespace, value, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            raise argparse.ArgumentError(self, "specify exactly one target ID")
        setattr(namespace, self.dest, value)


def _value_type(validate):
    def parse(value):
        try:
            return validate(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError(str(error)) from error
    return parse


def _download_id(value):
    try:
        return download_id(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _build_parser_with_commands():
    parser = argparse.ArgumentParser(prog="jd", add_help=False)
    # The CLI handles no-command help and no-argument TUI startup separately.
    sub = parser.add_subparsers(dest="command", required=False)

    commands = {}

    def command(name, description, **kwargs):
        target = sub.add_parser(name, description=description, help=description, **kwargs)
        commands[name] = target
        for alias in kwargs.get("aliases", ()):
            commands[alias] = target
        return target

    command("status", "Show a static snapshot of the download queue.")

    p_ls = command("list", 'List downloads with availability and reason.', aliases=["ls"])
    p_ls.add_argument("-d", "--detail", action="store_true", help="Show detailed link information")
    p_ls.add_argument("--search", metavar="TEXT", help="Case-insensitive name substring; package names also match in --packages view")
    p_ls.add_argument("--state", action="append", type=str.upper, choices=LINK_STATES, default=None, help="Filter by diagnostic state; repeat to match any listed state")
    p_ls.add_argument("--host", action="append", default=None, metavar="HOST", help="Case-insensitive exact host; repeat to match any listed host")
    p_ls.add_argument("--sort", choices=SORT_KEYS, help="Sort ascending; unknown values stay last")
    p_ls.add_argument("--reverse", action="store_true", help="Sort descending (requires --sort)")
    p_ls.add_argument("--packages", action="store_true", help="Summarize matched links by package, including matched/total link counts")

    p_show = command("show", 'Show raw link, package, URL, and diagnosis details.')
    p_show.add_argument("id", type=int, help="Download link ID shown by jd ls")
    p_show.add_argument("--json", action="store_true", dest="as_json", help="Print combined raw API data as JSON")

    p_why = command("why", 'Explain why a download is not progressing.')
    p_why.add_argument("id", type=int, help="Download link ID shown by jd ls")
    p_why.add_argument("--json", action="store_true", dest="as_json", help="Print diagnosis and source evidence as JSON")

    p_check = command("check", 'Request a fresh availability check for one link or the whole queue.')
    p_check.add_argument("id", nargs="?", type=int, help="Download link ID shown by jd ls")
    p_check.add_argument(
        "--all",
        action="store_true",
        dest="all_links",
        help="Queue a fresh online-status check for every download link",
    )
    p_check.add_argument("--json", action="store_true", dest="as_json", help="Print check result as JSON")

    p_gr = command("grabber", 'Inspect pending LinkGrabber links; filters only affect this listing.', allow_abbrev=False)
    p_gr.add_argument("-d", "--detail", action="store_true", help="Show detailed link information")

    p_gr.add_argument("--search", metavar="TEXT", help="Case-insensitive link name substring")
    p_gr.add_argument("--host", action="append", metavar="HOST", help="Exact host; repeat to match any host")
    p_gr.add_argument("--availability", action="append", type=str.upper, choices=AVAILABILITIES, help="JD availability; repeated values match any")
    p_gr.add_argument("--package", action="append", type=_download_id, metavar="ID", help="LinkGrabber package ID; repeat for multiple packages")
    p_gr.add_argument("--job", action="append", type=_download_id, metavar="ID", help="Add job ID returned by jd add; repeat for multiple jobs")
    p_gr.add_argument("--json", action="store_true", dest="as_json", help="Print queried link records as JSON (includes URLs and detail fields)")

    p_confirm = command("confirm", 'Move selected LinkGrabber links/packages to the queue. With no IDs, move all pending packages (legacy behavior). Does not explicitly start the controller; JD auto-start settings may apply.', allow_abbrev=False)
    p_confirm.add_argument("uuids", nargs="*", type=_download_id, metavar="ID", help="LinkGrabber link ID shown by jd grabber")
    p_confirm.add_argument("--package", action="append", type=_download_id, metavar="ID", help="LinkGrabber package ID shown by jd grabber; repeat for multiple packages")
    p_confirm.add_argument("--all", action="store_true", dest="all_links", help="Explicitly select all pending packages; cannot be combined with IDs")
    command("start", 'Start or resume the download controller.')
    command("stop", 'Stop the download controller.')
    command("clear", 'Remove finished links from the queue; downloaded files are kept.')
    command("version", 'Show JDSH and JDownloader core versions.')
    command("help", 'Show the command overview.')

    p_add = command("add", 'Add URLs to LinkGrabber from arguments, a UTF-8 file, or the macOS clipboard. Inspect jd grabber, then use jd confirm ID or jd confirm --package ID. Bare jd confirm moves all pending packages. Use jd start to start or resume the controller.')
    p_add.add_argument("--clipboard", action="store_true", help="Add links from the macOS clipboard")
    p_add.add_argument("-f", "--file", metavar="PATH", help="Read a UTF-8 text file containing one URL per line")
    p_add.add_argument("urls", nargs="*", metavar="URL", help="URLs to add; can be combined with --file and --clipboard")

    def selection_options(target):
        target.allow_abbrev = False
        target.add_argument("uuids", nargs="*", type=_download_id, metavar="ID", help="Download link IDs shown by jd ls")
        target.add_argument("--package", action="append", type=_download_id, default=None, metavar="ID", help="Package ID shown by jd ls --packages; repeat for multiple packages")

    descriptions = {
        "enable": "Enable selected download links or packages. Does not start the controller.",
        "disable": "Disable selected download links or packages.",
        "resume": "Ask JDownloader to resume selected links or packages. Does not explicitly start the controller.",
        "force": "Ask JDownloader to force selected links or packages to download; this may start downloads.",
    }
    for name, description in descriptions.items():
        selection_options(command(name, description))
    p_rm = command("remove", "Remove selected links or packages from the download queue; downloaded files are kept.", aliases=["rm"])
    selection_options(p_rm)

    p_reset = command("reset", "Reset selected downloads. JDownloader may delete existing files and discard progress; --yes is required.", allow_abbrev=False)
    selection_options(p_reset)
    p_reset.add_argument("--yes", action="store_true", help="Acknowledge that reset can delete existing files and discard download progress")

    p_priority = command("priority", "Set priority for selected links or packages; lowercase levels are accepted.", allow_abbrev=False)
    p_priority.add_argument("level", type=_value_type(priority_value), metavar="LEVEL", help="HIGHEST, HIGHER, HIGH, DEFAULT, LOW, LOWER, or LOWEST")
    selection_options(p_priority)

    p_rename = command("rename", "Rename one link or package; link renaming can also rename an existing downloaded file.", allow_abbrev=False)
    p_rename.add_argument("name", type=_value_type(nonblank_text), metavar="NAME", help="New name (quote names containing spaces)")
    rename_target = p_rename.add_mutually_exclusive_group(required=True)
    rename_target.add_argument("--link", action=_SingleTarget, type=_download_id, metavar="ID", help="One download link ID")
    rename_target.add_argument("--package", action=_SingleTarget, type=_download_id, metavar="ID", help="One package ID")

    p_directory = command("directory", "Change download destination for packages using a path on the JDownloader machine; JD may move existing files.", allow_abbrev=False)
    p_directory.add_argument("path", type=_value_type(directory_value), metavar="PATH", help="Absolute POSIX or Windows path; passed unchanged to JDownloader")
    p_directory.add_argument("--package", action="append", type=_download_id, required=True, metavar="ID", help="Package ID; repeat for multiple packages")

    p_rep = command("replace", 'Add a replacement URL with autostart, then remove the original link.')
    p_rep.add_argument("uuid", type=_download_id, metavar="ID", help="Original download link ID shown by jd ls")
    p_rep.add_argument("url", metavar="URL", help="Replacement URL")
    return parser, commands


def _build_parser():
    return _build_parser_with_commands()[0]


def _normalize_argv(argv):
    """Move supported input/selection options before positionals, preserving --.

    For hyphen-prefixed file names use --file=-name.txt or ./-name.txt.
    A standalone -- terminates options; it cannot escape a file option value.
    """
    argv = list(argv)
    if argv and argv[0] in SELECTION_OPTION_COMMANDS + ("confirm",):
        options, positionals = [], []
        index = 1
        while index < len(argv):
            arg = argv[index]
            if arg == "--":
                positionals.extend(argv[index:])
                break
            if arg == "--package":
                if index + 1 >= len(argv):
                    return argv
                value = argv[index + 1]
                # Let negative decimal IDs reach the validator; preserve real
                # option tokens so argparse can report a missing value.
                if value.startswith("-") and not (value[1:].isascii() and value[1:].isdecimal()):
                    return argv
                options.extend(argv[index:index + 2])
                index += 2
                continue
            if (arg == "--yes" and argv[0] == "reset") or (arg == "--all" and argv[0] == "confirm"):
                options.append(arg)
            elif arg.startswith("--package="):
                options.append(arg)
            else:
                # This bucket only preserves token order. Help/unknown options
                # remain options for argparse; do not consume them as IDs here.
                positionals.append(arg)
            index += 1
        return [argv[0]] + options + positionals
    if not argv or argv[0] != "add":
        return argv
    options = []
    positionals = []
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            positionals.extend(argv[index:])
            break
        if arg in ("-f", "--file"):
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return argv  # Let argparse report the missing option value.
            options.append(arg)
            index += 1
            options.append(argv[index])
        elif arg == "--clipboard" or arg.startswith("--file=") or arg.startswith("-f"):
            options.append(arg)
        else:
            positionals.append(arg)
        index += 1
    return ["add"] + options + positionals


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI arguments and validate command-specific combinations.

    This performs no configuration loading, input reading or API operations.
    Invalid arguments retain argparse stderr output and SystemExit(2). The
    CLI entry point handles global help and no-argument TUI startup separately.
    """
    parser, commands = _build_parser_with_commands()
    args = parser.parse_args(_normalize_argv(argv))
    if args.command in SELECTION_OPTION_COMMANDS and not args.uuids and not args.package:
        commands[args.command].error("requires download link IDs or --package ID")
    if args.command == "confirm" and args.all_links and (args.uuids or args.package):
        commands["confirm"].error("--all cannot be combined with link IDs or --package ID")
    if args.command == "grabber" and any(not host.strip() for host in (args.host or ())):
        commands["grabber"].error("--host requires a nonempty host name")
    if args.command == "reset" and not args.yes:
        commands["reset"].error("reset can delete existing files and discard progress; supply --yes to acknowledge")
    if args.command == "rename":
        try:
            rename_value(args.name, package=args.package is not None)
        except ValueError as error:
            commands["rename"].error(str(error))
    if args.command in ("list", "ls"):
        if any(not host.strip() for host in (args.host or ())):
            parser.error("--host requires a nonempty host name")
        if args.reverse and args.sort is None:
            parser.error("--reverse requires --sort")
        if args.packages and args.detail:
            parser.error("--packages and --detail cannot be combined; use jd ls -d for raw link details")
    if args.command == "add" and not args.urls and not args.clipboard and args.file is None:
        parser.error("jd add requires at least one URL, --clipboard, or --file")
    if args.command == "check":
        if args.id is None and not args.all_links:
            parser.error("jd check requires <id> or --all")
        if args.id is not None and args.all_links:
            parser.error("jd check accepts either <id> or --all, not both")
    return args
