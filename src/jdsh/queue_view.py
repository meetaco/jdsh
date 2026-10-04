"""Pure queue filtering, stable sorting, and matched-link package summaries."""

from collections import Counter

from .diagnostics import diagnose_link
from .stats import known_nonnegative, summarize_transfers, transfer_progress

LINK_STATES = ("RUNNING", "FINISHED", "DISABLED", "PROCESSING", "WAITING",
               "SKIPPED", "FINAL", "OFFLINE", "STATUS", "UNKNOWN")
SORT_KEYS = ("name", "id", "host", "size", "progress")


def filter_links(links, *, search=None, states=(), hosts=(), package_names=None):
    """Different filters intersect; repeated states/hosts are alternatives."""
    if search is None and not states and not hosts:
        return links
    needle = search.casefold() if search is not None else None
    states = {state.upper() for state in states}
    hosts = {host.casefold() for host in hosts}
    result = []
    for link in links:
        names = [str(link.get("name") or "")]
        if package_names is not None:
            names.append(str(package_names.get(link.get("packageUUID")) or ""))
        if needle is not None and not any(needle in name.casefold() for name in names):
            continue
        if states and diagnose_link(link)["state"] not in states:
            continue
        if hosts and str(link.get("host") or "").casefold() not in hosts:
            continue
        result.append(link)
    return result


def sort_rows(rows, *, sort=None, reverse=False):
    """Unknown keys stay last in either direction; ties preserve API order."""
    if sort is None:
        return rows

    def key(row):
        if sort == "size":
            return known_nonnegative(row.get("bytesTotal"))
        if sort == "progress":
            return transfer_progress(row).percent
        if sort == "id":
            return known_nonnegative(row.get("uuid"))
        if sort == "host" and "hosts" in row:
            value = ", ".join(row["hosts"])
        else:
            value = row.get(sort)
        return str(value).casefold() if value not in (None, "") else None

    known, unknown = [], []
    for row in rows:
        value = key(row)
        if value is None:
            unknown.append(row)
        else:
            known.append((value, row))
    return [row for _, row in sorted(known, key=lambda pair: pair[0], reverse=reverse)] + unknown


def summarize_packages(all_links, matched_links, packages):
    """Summaries describe matched links; total counts use the same link snapshot.

    Missing parent IDs share an explicit unknown-parent group. Missing metadata
    keeps the actual package ID and uses an unknown name rather than dropping links.
    Empty packages are omitted because they have no download links to summarize.
    """
    metadata = {pkg["uuid"]: pkg for pkg in packages if pkg.get("uuid") is not None}
    counts = Counter(link.get("packageUUID") for link in all_links)
    groups = {}
    for link in matched_links:
        groups.setdefault(link.get("packageUUID"), []).append(link)
    result = []
    for package_id, links in groups.items():
        summary = summarize_transfers(links)
        result.append({
            "uuid": package_id,
            "name": metadata.get(package_id, {}).get("name"),
            "matchedCount": len(links),
            "linkCount": counts[package_id],
            "bytesLoaded": summary.loaded,
            "bytesTotal": summary.total,
            "states": dict(Counter(diagnose_link(link)["state"] for link in links)),
            "hosts": sorted({str(link["host"]) for link in links if link.get("host")}),
        })
    return result
