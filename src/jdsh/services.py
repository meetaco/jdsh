"""Download operations shared by CLI and TUI; no terminal output or process exits."""

import logging
import time
from typing import Any, Dict, Iterable, List, Tuple

from .client import (
    CHECK_LINK_STATE_QUERY,
    DOWNLOAD_LINK_STATE_QUERY,
    DOWNLOAD_PACKAGE_STATE_QUERY,
    GRABBER_LINK_STATE_QUERY,
    LIST_LINK_STATE_QUERY,
    STATUS_LINK_STATE_QUERY,
    get_download_urls,
    start_online_status_check,
)
# available_status preserves the former CLI helper: non-dict states return None.
from .diagnostics import available_status, diagnose_link
from .errors import ServiceError
from .download_selection import download_id, select_downloads
from .download_values import priority_value, rename_value, directory_value
from .queue_view import filter_links, normalize_search, sort_rows, summarize_packages

CHECK_TIMEOUT_SECONDS = 30.0
CHECK_POLL_INTERVAL_SECONDS = 0.1
CHECK_FAST_COMPLETION_GRACE_SECONDS = 1.0


# These thin operations preserve SDK failures for the CLI error boundary. They
# return data only; input collection and success/fallback messages stay in CLI.
def download_status(device) -> Tuple[str, List[Dict[str, Any]]]:
    state = device.downloadcontroller.get_current_state()
    # Query values are immutable scalar flags, so a shallow copy is sufficient.
    links = device.downloads.query_links([STATUS_LINK_STATE_QUERY.copy()])
    return state, links


def list_downloads(device, *, detail: bool = False, search=None, states=(),
                   hosts=(), sort=None, reverse=False) -> List[Dict[str, Any]]:
    search = normalize_search(search)
    query = DOWNLOAD_LINK_STATE_QUERY if detail else LIST_LINK_STATE_QUERY
    query = query.copy()
    if search is not None or states or hosts or sort is not None:
        query.update(startAt=0, maxResults=-1)
    links = device.downloads.query_links([query])
    return sort_rows(filter_links(links, search=search, states=states, hosts=hosts),
                     sort=sort, reverse=reverse)


def list_download_packages(device, *, search=None, states=(), hosts=(),
                           sort=None, reverse=False) -> List[Dict[str, Any]]:
    query = dict(LIST_LINK_STATE_QUERY, startAt=0, maxResults=-1)
    links = device.downloads.query_links([query])
    if not links:
        return []
    # Names and IDs are always returned by queryPackages; request all metadata
    # rows without fetching unrelated optional fields such as comments or paths.
    packages = device.downloads.query_packages([{"startAt": 0, "maxResults": -1}])
    names = {pkg["uuid"]: pkg.get("name") for pkg in packages if pkg.get("uuid") is not None}
    matched = filter_links(links, search=search, states=states, hosts=hosts,
                           package_names=names)
    return sort_rows(summarize_packages(links, matched, names), sort=sort,
                     reverse=reverse, packages=True)


def list_grabber_links(device) -> List[Dict[str, Any]]:
    return device.linkgrabber.query_links([GRABBER_LINK_STATE_QUERY.copy()])


def add_to_grabber(device, links: Iterable[str]) -> None:
    """Submit the collected links in their original order without starting them."""
    device.linkgrabber.add_links([{
        "links": ",".join(links), "autostart": False, "priority": "DEFAULT",
    }])


def confirm_grabber(device) -> int:
    """Move all pending packages in one call; return their count after success."""
    packages = device.linkgrabber.query_packages([{"uuid": True}])
    if not packages:
        return 0
    device.linkgrabber.move_to_downloadlist([], [package["uuid"] for package in packages])
    return len(packages)


def apply_download_action(device, action, link_ids=(), package_ids=()):
    """Submit one explicit request; returned selection counts are not effect counts."""
    if action not in ("enable", "disable", "resume", "force", "remove"):
        raise ValueError(f"Unsupported download action: {action}")
    selection = select_downloads(link_ids, package_ids)
    links, packages = list(selection.link_ids), list(selection.package_ids)
    if action in ("enable", "disable"):
        result = device.downloads.set_enabled(action == "enable", links, packages)
    elif action == "resume":
        result = device.action("/downloadsV2/resumeLinks", [links, packages])
    elif action == "force":
        result = device.downloads.force_download(links, packages)
    else:
        result = device.downloads.remove_links(links, packages)
    if result is False:
        raise ServiceError(f"JDownloader did not accept the {action} request")
    return selection


def remove_downloads(device, link_ids, package_ids=()):
    return apply_download_action(device, "remove", link_ids, package_ids)


def _submit_download_setting(device, operation, endpoint, params, selection):
    result = device.action(endpoint, params)
    if result is False:
        raise ServiceError(f"JDownloader did not accept the {operation} request")
    return selection


def reset_downloads(device, link_ids=(), package_ids=(), *, confirmed=False):
    selection = select_downloads(link_ids, package_ids)
    if confirmed is not True:
        raise ValueError("reset can delete existing files and discard progress; explicit confirmation is required")
    return _submit_download_setting(device, "reset", "/downloadsV2/resetLinks",
                                    [list(selection.link_ids), list(selection.package_ids)], selection)


def set_download_priority(device, level, link_ids=(), package_ids=()):
    selection = select_downloads(link_ids, package_ids)
    level = priority_value(level)
    return _submit_download_setting(device, "priority", "/downloadsV2/setPriority",
                                    [level, list(selection.link_ids), list(selection.package_ids)], selection)


def rename_download(device, name, link_ids=(), package_ids=()):
    selection = select_downloads(link_ids, package_ids)
    if len(selection.link_ids) + len(selection.package_ids) != 1:
        raise ValueError("rename requires exactly one link ID or one package ID")
    package = bool(selection.package_ids)
    name = rename_value(name, package=package)
    endpoint = "/downloadsV2/renamePackage" if package else "/downloadsV2/renameLink"
    target = selection.package_ids[0] if package else selection.link_ids[0]
    return _submit_download_setting(device, "rename", endpoint, [target, name], selection)


def set_download_directory(device, path, package_ids):
    selection = select_downloads((), package_ids)
    path = directory_value(path)
    return _submit_download_setting(device, "directory", "/downloadsV2/setDownloadDirectory",
                                    [path, list(selection.package_ids)], selection)


def start_downloads(device) -> None:
    device.downloadcontroller.start_downloads()


def stop_downloads(device) -> None:
    device.downloadcontroller.stop_downloads()


def clear_finished_downloads(device) -> None:
    device.downloads.cleanup("DELETE_FINISHED", "REMOVE_LINKS_ONLY", "ALL", [], [])


def core_revision(device) -> Any:
    return device.action("/jd/getCoreRevision", [])


class ShowError(ServiceError):
    pass


class CheckError(ServiceError):
    pass


class WhyError(ServiceError):
    pass


def _query_download_link(device, link_id, fields, error_type):
    query = fields.copy()
    query["linkUUIDs"] = [link_id]
    try:
        links = device.downloads.query_links([query])
        return next((link for link in links if link.get("uuid") == link_id), None)
    except Exception as e:
        raise error_type(f"Failed to query download link: {e}") from e


def show_download(device, link_id):
    link = _query_download_link(device, link_id, DOWNLOAD_LINK_STATE_QUERY, ShowError)

    if link is None:
        raise ShowError(f"Download link ID not found: {link_id}")

    package = None
    package_uuid = link.get("packageUUID")
    if package_uuid is not None:
        package_query = DOWNLOAD_PACKAGE_STATE_QUERY.copy()
        package_query["packageUUIDs"] = [package_uuid]
        try:
            packages = device.downloads.query_packages([package_query])
            package = next((pkg for pkg in packages if pkg.get("uuid") == package_uuid), None)
        except Exception as e:
            raise ShowError(f"Failed to query parent package: {e}") from e

    try:
        download_urls = get_download_urls(device, [link_id])
    except Exception as e:
        raise ShowError(f"Failed to query download URLs: {e}") from e

    return {
        "link": link,
        "package": package,
        "downloadUrls": download_urls,
        "diagnosis": diagnose_link(link),
    }


def _query_check_link(device, link_id):
    return _query_download_link(device, link_id, CHECK_LINK_STATE_QUERY, CheckError)


def _wait_for_online_check(device, link_id, initial_status, *, clock=None, sleep=None):
    clock = time.monotonic if clock is None else clock
    sleep = time.sleep if sleep is None else sleep
    initial_id = (initial_status or {}).get("id")
    started_at = clock()
    deadline = started_at + CHECK_TIMEOUT_SECONDS
    saw_unchecked = initial_id == "UNCHECKED"

    while True:
        link = _query_check_link(device, link_id)
        if link is None:
            raise CheckError(f"Download link ID disappeared during check: {link_id}")

        status = available_status(link)
        status_id = (status or {}).get("id")
        now = clock()

        if status_id == "UNCHECKED":
            saw_unchecked = True
        elif status_id is not None:
            if saw_unchecked or status_id != initial_id:
                return link
            # The force re-check can complete before polling observes UNCHECKED.
            # Once the worker has had a short grace period, the latest final
            # status is the best completion signal the API exposes.
            if now - started_at >= CHECK_FAST_COMPLETION_GRACE_SECONDS:
                return link

        if now >= deadline:
            raise CheckError(f"Online status check timed out after {CHECK_TIMEOUT_SECONDS:g}s")
        sleep(CHECK_POLL_INTERVAL_SECONDS)


def check_download(device, link_id, *, clock=None, sleep=None):
    """Start a re-check and await availability using injectable polling functions."""
    initial_link = _query_check_link(device, link_id)
    if initial_link is None:
        raise CheckError(f"Download link ID not found: {link_id}")

    initial_status = available_status(initial_link)
    try:
        start_online_status_check(device, [link_id])
    except Exception as e:
        raise CheckError(f"Failed to start online status check: {e}") from e

    link = _wait_for_online_check(device, link_id, initial_status, clock=clock, sleep=sleep)
    return {
        "uuid": link.get("uuid"),
        "name": link.get("name"),
        "availableStatus": available_status(link),
    }


def check_all_downloads(device):
    try:
        links = device.downloads.query_links([{"uuid": True}])
        link_ids = list(dict.fromkeys(
            link.get("uuid") for link in links if link.get("uuid") is not None
        ))
    except Exception as e:
        raise CheckError(f"Failed to query download links: {e}") from e

    if not link_ids:
        return {"started": False, "linkCount": 0}

    try:
        # Submit the whole selection in one call so JDownloader owns host-level
        # queueing, mass link checks, concurrency, and plugin-specific throttling.
        start_online_status_check(device, link_ids)
    except Exception as e:
        raise CheckError(f"Failed to start online status check: {e}") from e

    return {"started": True, "linkCount": len(link_ids)}


def explain_download(device, link_id):
    link = _query_download_link(device, link_id, DOWNLOAD_LINK_STATE_QUERY, WhyError)

    if link is None:
        raise WhyError(f"Download link ID not found: {link_id}")

    controller_state = None
    try:
        controller_state = device.downloadcontroller.get_current_state()
    except Exception:
        logging.getLogger(__name__).debug("Controller state unavailable", exc_info=True)

    return {
        "uuid": link.get("uuid"),
        "name": link.get("name"),
        "controllerState": controller_state,
        "diagnosis": diagnose_link(link, controller_state=controller_state),
        "status": link.get("status"),
        "advancedStatus": link.get("advancedStatus"),
        "extractionStatus": link.get("extractionStatus"),
    }


class ReplacementError(ServiceError):
    """Replacing a link failed, possibly after removal of the original."""


def replace_download(device, link_id, url):
    """Validate before any mutation; add the replacement before removing original."""
    link_id = download_id(link_id)
    try:
        result = device.linkgrabber.add_links([{
            "links": url, "autostart": True, "packageName": f"Rep_{link_id}",
        }])
        if result is False:
            raise ServiceError("JDownloader did not accept the replacement URL")
    except Exception as e:
        raise ReplacementError(
            f"Failed to add replacement for link {link_id}; original was not removed: {e}"
        ) from e
    try:
        remove_downloads(device, [link_id])
    except Exception as e:
        raise ReplacementError(
            f"Replacement was added, but removing original link {link_id} failed: {e}. "
            "Both entries may remain; inspect 'jd ls' and 'jd grabber' before retrying."
        ) from e
