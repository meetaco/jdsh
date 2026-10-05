"""Filter LinkGrabber's availability values without download-state inference."""

from .download_selection import download_id
from .queue_view import normalize_search

AVAILABILITIES = ("ONLINE", "OFFLINE", "UNKNOWN", "TEMP_UNKNOWN")


def filter_grabber_links(links, *, search=None, hosts=(), availability=(), package_ids=()):
    search = normalize_search(search)
    if search is None and not hosts and not availability and not package_ids:
        return links
    needle = search.casefold() if search is not None else None
    hosts = {host.strip().casefold() for host in hosts}
    availability = {value.upper() for value in availability}
    packages = set(package_ids)
    result = []
    for link in links:
        if needle is not None and needle not in str(link.get("name") or "").casefold():
            continue
        if hosts and str(link.get("host") or "").casefold() not in hosts:
            continue
        # Missing availability is not a server-provided UNKNOWN value.
        if availability and str(link.get("availability") or "").upper() not in availability:
            continue
        if packages:
            try:
                package_id = download_id(link.get("packageUUID"))
            except ValueError:
                # A malformed/missing parent is not evidence of a package match.
                continue
            if package_id not in packages:
                continue
        result.append(link)
    return result
