import argparse
import json
import logging
import os
from contextlib import contextmanager
import sys

from . import config, rendering, services, tui, url_inputs
from .errors import JDShError
from .client import JDClient


def print_help(*, console=None):
    rendering.print_help(console=console)


def cmd_status(device, args, *, console=None):
    state, links = services.download_status(device)
    rendering.render_status(state, links, console=console)


def cmd_show(device, args, *, console=None):
    payload = services.show_download(device, args.id)

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return

    rendering.render_show(payload, args.id, console=console)


def cmd_check(device, args, *, console=None):
    if getattr(args, "all_links", False):
        payload = services.check_all_downloads(device)

        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            rendering.render_check_all(payload, console=console)
        return

    payload = services.check_download(device, args.id)

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return

    rendering.render_check(payload, console=console)


def cmd_why(device, args, *, console=None):
    payload = services.explain_download(device, args.id)

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return

    rendering.render_why(payload, console=console)


def cmd_list(device, args, *, console=None):
    links = services.list_downloads(device, detail=args.detail)
    rendering.render_list(links, detail=args.detail, console=console)


def cmd_grabber(device, args, *, console=None):
    links = services.list_grabber_links(device)
    rendering.render_grabber(links, detail=args.detail, console=console)


def cmd_add(device, args, *, console=None):
    links = url_inputs.collect_links(
        args.urls,
        file_path=getattr(args, "file", None),
        use_clipboard=args.clipboard,
    )
    services.add_to_grabber(device, links)
    rendering.render_message("Added links to Grabber. Run 'jd confirm' to start.", console=console)


def cmd_confirm(device, _, *, console=None):
    count = services.confirm_grabber(device)
    if not count:
        rendering.render_message("No pending packages.", console=console)
        return
    rendering.render_message(f"Confirmed {count} packages.", console=console)


def cmd_remove(device, args, *, console=None):
    services.remove_downloads(device, args.uuids)
    rendering.render_message(f"Removed {len(args.uuids)} items.", console=console)


def cmd_replace(device, args, *, console=None):
    services.replace_download(device, args.uuid, args.url)
    rendering.render_message("Link replaced and restarted.", console=console)


def cmd_simple(device, args, *, console=None):
    cmds = {
        'start': services.start_downloads,
        'stop': services.stop_downloads,
        'clear': services.clear_finished_downloads
    }
    cmds[args.command](device)
    rendering.render_message(f"Command executed: {args.command}", console=console)


def cmd_version(device, args, *, console=None):
    rendering.render_message(f"JDSH v{config.VERSION}", console=console)
    try:
        revision = services.core_revision(device)
    except Exception:
        logging.getLogger(__name__).debug("Core version unavailable", exc_info=True)
        revision = "Unknown"
    rendering.render_message(f"JD Core: {revision}", console=console)


def _build_parser():
    parser = argparse.ArgumentParser(prog="jd", add_help=False)
    sub = parser.add_subparsers(dest="command")

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
    """Move add's options before positionals, preserving option values and --."""
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


def _parse_args(argv):
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


def _execute(action, *args):
    """Present operation failures at the CLI boundary; preserve parser exits."""
    try:
        return action(*args)
    except Exception as e:
        logging.getLogger(__name__).debug("Command failed", exc_info=True)
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1) from e


def _main(argv, console=None):
    if "-h" in argv or "--help" in argv:
        print_help(console=console)
        return
    args = _parse_args(argv) if argv else None
    if args is not None and args.command in ["help", None]:
        print_help(console=console)
        return

    settings = config.load_settings()
    client = JDClient(settings)
    device = client.connect()
    if args is None:
        tui.run(client, console=console)
        return

    actions = {
        'status': cmd_status,
        'list': cmd_list, 'ls': cmd_list,
        'show': cmd_show,
        'why': cmd_why,
        'check': cmd_check,
        'grabber': cmd_grabber, 'confirm': cmd_confirm,
        'add': cmd_add, 'remove': cmd_remove, 'rm': cmd_remove,
        'replace': cmd_replace, 'start': cmd_simple,
        'stop': cmd_simple, 'clear': cmd_simple,
        'version': cmd_version,
    }
    handler = actions.get(args.command)
    if handler is None:
        raise JDShError(f"Unsupported command: {args.command}")
    handler(device, args, console=console)


@contextmanager
def _debug_logging():
    """Enable only JDSH debug output and restore embedding application's logger."""
    if os.environ.get("JDSH_DEBUG") != "1":
        yield
        return
    logger = logging.getLogger("jdsh")
    previous_level, previous_propagate = logger.level, logger.propagate
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        yield
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def main(argv=None, *, console=None):
    with _debug_logging():
        _execute(_main, sys.argv[1:] if argv is None else list(argv), console)


if __name__ == "__main__":
    main()
