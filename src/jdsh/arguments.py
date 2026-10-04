"""Command definitions and argument validation, independent of CLI execution."""

import argparse
from typing import Sequence

from .queue_view import LINK_STATES, SORT_KEYS


def _build_parser():
    parser = argparse.ArgumentParser(prog="jd", add_help=False)
    # The CLI handles no-command help and no-argument TUI startup separately.
    sub = parser.add_subparsers(dest="command", required=False)

    def command(name, description, **kwargs):
        return sub.add_parser(name, description=description, help=description, **kwargs)

    command("status", "Show a static snapshot of the download queue.")

    p_ls = command("list", 'List downloads with availability and reason.', aliases=["ls"])
    p_ls.add_argument("-d", "--detail", action="store_true", help="Show detailed link information")
    p_ls.add_argument("--search", metavar="TEXT", help="Case-insensitive name substring; package names also match in --packages view")
    p_ls.add_argument("--state", action="append", type=str.upper, choices=LINK_STATES, default=[], help="Filter by diagnostic state; repeat to match any listed state")
    p_ls.add_argument("--host", action="append", default=[], metavar="HOST", help="Case-insensitive exact host; repeat to match any listed host")
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

    p_gr = command("grabber", 'List pending links in LinkGrabber.')
    p_gr.add_argument("-d", "--detail", action="store_true", help="Show detailed link information")

    command("confirm", 'Move all pending packages to the download queue. Use jd start to start or resume the download controller.')
    command("start", 'Start or resume the download controller.')
    command("stop", 'Stop the download controller.')
    command("clear", 'Remove finished links from the queue; downloaded files are kept.')
    command("version", 'Show JDSH and JDownloader core versions.')
    command("help", 'Show the command overview.')

    p_add = command("add", 'Add URLs to LinkGrabber from arguments, a UTF-8 file, or the macOS clipboard. Then use jd confirm to move pending links to the queue and jd start to start or resume the download controller.')
    p_add.add_argument("--clipboard", action="store_true", help="Add links from the macOS clipboard")
    p_add.add_argument("-f", "--file", metavar="PATH", help="Read a UTF-8 text file containing one URL per line")
    p_add.add_argument("urls", nargs="*", metavar="URL", help="URLs to add; can be combined with --file and --clipboard")

    p_rm = command("remove", 'Remove the specified download links from the queue.', aliases=["rm"])
    p_rm.add_argument("uuids", nargs="+", metavar="ID", help="Download link IDs shown by jd ls")

    p_rep = command("replace", 'Add a replacement URL with autostart, then remove the original link.')
    p_rep.add_argument("uuid", metavar="ID", help="Original download link ID shown by jd ls")
    p_rep.add_argument("url", metavar="URL", help="Replacement URL")
    return parser


def _normalize_argv(argv):
    """Move add's options before positionals, preserving option values and --.

    For hyphen-prefixed file names use --file=-name.txt or ./-name.txt.
    A standalone -- terminates options; it cannot escape a file option value.
    """
    argv = list(argv)
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
    parser = _build_parser()
    args = parser.parse_args(_normalize_argv(argv))
    if args.command in ("list", "ls"):
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
