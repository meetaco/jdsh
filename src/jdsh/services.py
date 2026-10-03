"""Download operations shared by CLI and TUI; no terminal output or process exits."""

import time

from .client import (
    CHECK_LINK_STATE_QUERY,
    DOWNLOAD_LINK_STATE_QUERY,
    DOWNLOAD_PACKAGE_STATE_QUERY,
    get_download_urls,
    start_online_status_check,
)
# available_status preserves the former CLI helper: non-dict states return None.
from .diagnostics import available_status, diagnose_link

CHECK_TIMEOUT_SECONDS = 30.0
CHECK_POLL_INTERVAL_SECONDS = 0.1
CHECK_FAST_COMPLETION_GRACE_SECONDS = 1.0


class ShowError(RuntimeError):
    pass


class CheckError(RuntimeError):
    pass


class WhyError(RuntimeError):
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
        pass

    return {
        "uuid": link.get("uuid"),
        "name": link.get("name"),
        "controllerState": controller_state,
        "diagnosis": diagnose_link(link, controller_state=controller_state),
        "status": link.get("status"),
        "advancedStatus": link.get("advancedStatus"),
        "extractionStatus": link.get("extractionStatus"),
    }
