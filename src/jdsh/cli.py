import json
import logging
import os
from contextlib import contextmanager
import sys

from . import arguments, config, rendering, services, tui, url_inputs
from .errors import JDShError
from .queue_view import normalize_search
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
    # Accept older embedded callers whose namespace only has the detail flag.
    detail = getattr(args, "detail", False)
    options = {
        "search": normalize_search(getattr(args, "search", None)),
        "states": getattr(args, "state", None) or (),
        "hosts": getattr(args, "host", None) or (),
        "sort": getattr(args, "sort", None),
        "reverse": getattr(args, "reverse", False),
    }
    filtered = options["search"] is not None or bool(options["states"] or options["hosts"])
    if getattr(args, "packages", False):
        packages = services.list_download_packages(device, **options)
        rendering.render_packages(packages, filtered=filtered, console=console)
    else:
        links = services.list_downloads(device, detail=detail, **options)
        rendering.render_list(links, detail=detail, filtered=filtered, console=console)


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
    rendering.render_message("Added links to Grabber. Run 'jd confirm' to move them to the queue, then 'jd start' to start or resume downloads.", console=console)


def cmd_confirm(device, _, *, console=None):
    count = services.confirm_grabber(device)
    if not count:
        rendering.render_message("No pending packages.", console=console)
        return
    rendering.render_message(f"Moved {count} packages to the download queue. Run 'jd start' to start or resume downloads.", console=console)


def cmd_remove(device, args, *, console=None):
    selection = services.remove_downloads(device, args.uuids, getattr(args, "package", None) or ())
    _render_selection_request("remove", selection, console=console)


def _render_selection_request(action, selection, *, console=None):
    links, packages = len(selection.link_ids), len(selection.package_ids)
    link_label = "link ID" if links == 1 else "link IDs"
    package_label = "package ID" if packages == 1 else "package IDs"
    rendering.render_message(
        f"Submitted {action} request for {links} {link_label} and "
        f"{packages} {package_label}.", console=console,
    )


def cmd_download_action(device, args, *, console=None):
    selection = services.apply_download_action(
        device, args.command, args.uuids, getattr(args, "package", None) or (),
    )
    _render_selection_request(args.command, selection, console=console)


def cmd_download_setting(device, args, *, console=None):
    if args.command == "reset":
        selection = services.reset_downloads(device, args.uuids, args.package or (), confirmed=args.yes)
    elif args.command == "priority":
        selection = services.set_download_priority(device, args.level, args.uuids, args.package or ())
    elif args.command == "rename":
        selection = services.rename_download(device, args.name,
                                            [args.link] if args.link is not None else (),
                                            [args.package] if args.package is not None else ())
    elif args.command == "directory":
        selection = services.set_download_directory(device, args.path, args.package)
    else:
        raise JDShError(f"Unsupported download setting: {args.command}")
    _render_selection_request(args.command, selection, console=console)


def cmd_replace(device, args, *, console=None):
    services.replace_download(device, args.uuid, args.url)
    rendering.render_message("Replacement URL added and original queue entry removed.", console=console)


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


def _parse_args(argv):
    """Compatibility entry point; argument parsing lives in arguments."""
    return arguments.parse_args(argv)


def _execute(action, *args):
    """Present operation failures at the CLI boundary; preserve parser exits."""
    try:
        return action(*args)
    except Exception as e:
        logging.getLogger(__name__).debug("Command failed", exc_info=True)
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1) from e


def _main(argv, console=None):
    if argv in (["-h"], ["--help"]):
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
        'enable': cmd_download_action, 'disable': cmd_download_action,
        'resume': cmd_download_action, 'force': cmd_download_action,
        'reset': cmd_download_setting, 'priority': cmd_download_setting,
        'rename': cmd_download_setting, 'directory': cmd_download_setting,
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
