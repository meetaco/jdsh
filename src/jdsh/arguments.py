"""Command definitions and argument validation, independent of CLI execution."""

import argparse
from typing import Sequence


def _build_parser():
    parser = argparse.ArgumentParser(prog="jd", add_help=False)
    # The CLI handles no-command help and no-argument TUI startup separately.
    sub = parser.add_subparsers(dest="command", required=False)

    sub.add_parser("status")

    p_ls = sub.add_parser("list", aliases=["ls"])
    p_ls.add_argument("-d", "--detail", action="store_true")

    p_show = sub.add_parser("show")
    p_show.add_argument("id", type=int, help="Download link ID shown by jd ls")
    p_show.add_argument("--json", action="store_true", dest="as_json", help="Print combined raw API data as JSON")

    p_why = sub.add_parser("why")
    p_why.add_argument("id", type=int, help="Download link ID shown by jd ls")
    p_why.add_argument("--json", action="store_true", dest="as_json", help="Print diagnosis and source evidence as JSON")

    p_check = sub.add_parser("check")
    p_check.add_argument("id", nargs="?", type=int, help="Download link ID shown by jd ls")
    p_check.add_argument(
        "--all",
        action="store_true",
        dest="all_links",
        help="Queue a fresh online-status check for every download link",
    )
    p_check.add_argument("--json", action="store_true", dest="as_json", help="Print check result as JSON")

    p_gr = sub.add_parser("grabber")
    p_gr.add_argument("-d", "--detail", action="store_true")

    sub.add_parser("confirm")
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("clear")
    sub.add_parser("version")
    sub.add_parser("help")

    p_add = sub.add_parser("add")
    p_add.add_argument("--clipboard", action="store_true", help="Add links from the macOS clipboard")
    p_add.add_argument("-f", "--file", metavar="PATH", help="Read a UTF-8 text file containing one URL per line")
    p_add.add_argument("urls", nargs="*")

    p_rm = sub.add_parser("remove", aliases=["rm"])
    p_rm.add_argument("uuids", nargs="+")

    p_rep = sub.add_parser("replace")
    p_rep.add_argument("uuid")
    p_rep.add_argument("url")
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
    if args.command == "add" and not args.urls and not args.clipboard and args.file is None:
        parser.error("jd add requires at least one URL, --clipboard, or --file")
    if args.command == "check":
        if args.id is None and not args.all_links:
            parser.error("jd check requires <id> or --all")
        if args.id is not None and args.all_links:
            parser.error("jd check accepts either <id> or --all, not both")
    return args
