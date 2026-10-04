import argparse
import json
import logging
import os
from contextlib import contextmanager
import sys

from . import clipboard, config, rendering, services, tui
from .errors import JDShError
from .client import (
    DOWNLOAD_LINK_STATE_QUERY,
    JDClient,
    LIST_LINK_STATE_QUERY,
)


def print_help():
    rendering.print_help()


def cmd_status(device, args):
    state = device.downloadcontroller.get_current_state()
    links = device.downloads.query_links([{
        "name": True, "bytesLoaded": True, "bytesTotal": True,
        "speed": True, "running": True, "eta": True, "status": True,
    }])
    rendering.render_status(state, links)


def cmd_show(device, args):
    payload = services.show_download(device, args.id)

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return

    rendering.render_show(payload, args.id)


def cmd_check(device, args):
    if getattr(args, "all_links", False):
        payload = services.check_all_downloads(device)

        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        elif payload["started"]:
            print(
                f"Started online status check for {payload['linkCount']} links. "
                "JDownloader will process them in the background."
            )
        else:
            print("No download links to check.")
        return

    payload = services.check_download(device, args.id)

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return

    rendering.render_check(payload)


def cmd_why(device, args):
    payload = services.explain_download(device, args.id)

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return

    rendering.render_why(payload)


def cmd_list(device, args):
    query = DOWNLOAD_LINK_STATE_QUERY if args.detail else LIST_LINK_STATE_QUERY
    links = device.downloads.query_links([query.copy()])
    rendering.render_list(links, detail=args.detail)


def cmd_grabber(device, args):
    links = device.linkgrabber.query_links([{"name": True, "uuid": True, "url": True}])
    rendering.render_grabber(links, detail=args.detail)


def cmd_add(device, args):
    file_path = getattr(args, "file", None)
    links = " ".join(args.urls).split()
    if file_path is not None:
        try:
            with open(file_path, encoding="utf-8-sig") as url_file:
                links.extend(line.strip() for line in url_file if line.strip())
        except (OSError, UnicodeError) as e:
            raise JDShError(f"cannot read URL file {file_path!r}: {e}") from e

    if args.clipboard:
        links.extend(clipboard.read_clipboard_links())

    if file_path is not None or args.clipboard:
        links = clipboard.dedupe_preserve_order(links)
    if not links:
        raise JDShError("no URLs to add")
    link_str = ",".join(links)

    device.linkgrabber.add_links([{"links": link_str, "autostart": False, "priority": "DEFAULT"}])
    print("Added links to Grabber. Run 'jd confirm' to start.")


def cmd_confirm(device, _):
    pkgs = device.linkgrabber.query_packages([{"uuid": True}])
    if not pkgs: return print("No pending packages.")
    device.linkgrabber.move_to_downloadlist([], [p['uuid'] for p in pkgs])
    print(f"Confirmed {len(pkgs)} packages.")


def cmd_remove(device, args):
    device.downloads.remove_links(args.uuids, [])
    print(f"Removed {len(args.uuids)} items.")


def cmd_replace(device, args):
    services.replace_download(device, args.uuid, args.url)
    print("Link replaced and restarted.")


def cmd_simple(device, args):
    cmds = {
        'start': device.downloadcontroller.start_downloads,
        'stop': device.downloadcontroller.stop_downloads,
        'clear': lambda: device.downloads.cleanup("DELETE_FINISHED", "REMOVE_LINKS_ONLY", "ALL", [], [])
    }
    cmds[args.command]()
    print(f"Command executed: {args.command}")


def cmd_version(device, args):
    print(f"JDSH v{config.VERSION}")
    try: print(f"JD Core: {device.action('/jd/getCoreRevision', [])}")
    except Exception:
        logging.getLogger(__name__).debug("Core version unavailable", exc_info=True)
        print("JD Core: Unknown")


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


def _main(argv):
    if "-h" in argv or "--help" in argv:
        print_help()
        return
    args = _parse_args(argv) if argv else None
    if args is not None and args.command in ["help", None]:
        print_help()
        return

    settings = config.load_settings()
    client = JDClient(settings)
    device = client.connect()
    if args is None:
        tui.run(client)
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
    handler(device, args)


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


def main(argv=None):
    with _debug_logging():
        _execute(_main, sys.argv[1:] if argv is None else list(argv))


if __name__ == "__main__":
    main()
