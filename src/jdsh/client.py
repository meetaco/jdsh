import sys
from myjdapi import Myjdapi
from . import config


COMPACT_LINK_STATE_QUERY = {
    "name": True,
    "bytesLoaded": True,
    "bytesTotal": True,
    "running": True,
    "status": True,
    "finished": True,
    "enabled": True,
    "skipped": True,
    "uuid": True,
}

# Keep diagnostic output broad, but deliberately omit the upstream `password`
# field so `jd ls -d` and `jd show --json` do not expose download credentials.
DOWNLOAD_LINK_STATE_QUERY = {
    **COMPACT_LINK_STATE_QUERY,
    "speed": True,
    "eta": True,
    "advancedStatus": True,
    "extractionStatus": True,
    "host": True,
    "url": True,
    "addedDate": True,
    "comment": True,
    "finishedDate": True,
    "priority": True,
}

# Keep availability refreshes narrow: jd check only needs the fields required
# to identify the link and read advancedStatus.AvailableStatus.
CHECK_LINK_STATE_QUERY = {
    "name": True,
    "uuid": True,
    "advancedStatus": True,
}

# JDownloader's PackageQueryStorable.FULL fields. Package queries do not expose
# the link password field, so the full package diagnostic surface is safe to use.
DOWNLOAD_PACKAGE_STATE_QUERY = {
    "bytesLoaded": True,
    "bytesTotal": True,
    "childCount": True,
    "comment": True,
    "enabled": True,
    "eta": True,
    "finished": True,
    "hosts": True,
    "priority": True,
    "running": True,
    "saveTo": True,
    "speed": True,
    "status": True,
}

# Keep the same order as JDownloader's UrlDisplayType enum.
DOWNLOAD_URL_DISPLAY_TYPES = ("CUSTOM", "REFERRER", "ORIGIN", "CONTAINER", "CONTENT")

# Keep the high-frequency TUI poll limited to fields it actually renders.
# Diagnostic-only fields such as advancedStatus remain available to `jd ls -d`
# without paying their construction/payload cost on every TUI refresh.
TUI_LINK_STATE_QUERY = {
    "name": True,
    "bytesLoaded": True,
    "bytesTotal": True,
    "speed": True,
    "running": True,
    "eta": True,
    "status": True,
    "finished": True,
    "enabled": True,
}


def get_download_urls(device, link_ids, package_ids=()):
    """Return the raw getDownloadUrls response for every URL display type."""
    # SelectionInfoUtils.getURLs stops at the first matching type for each link,
    # so querying all types in one call would only return the highest-priority
    # match. Query each type separately to preserve all URL views JDownloader can
    # expose. The outer keys are the requested types; if JDownloader's optional
    # UseUrlOrderForMyJD setting is enabled, JDownloader may override that request.
    link_ids = list(link_ids)
    package_ids = list(package_ids)
    responses = {}
    for url_type in DOWNLOAD_URL_DISPLAY_TYPES:
        responses[url_type] = device.action(
            "/downloadsV2/getDownloadUrls",
            [link_ids, package_ids, [url_type]],
        )
    return responses


def start_online_status_check(device, link_ids, package_ids=()):
    """Force JDownloader to re-check the selected download links asynchronously."""
    return device.action(
        "/downloadsV2/startOnlineStatusCheck",
        [list(link_ids), list(package_ids)],
    )


class JDClient:
    def __init__(self):
        self.api = Myjdapi()
        self.api.set_app_key(config.APP_KEY)
        self.device = None

    def connect(self):
        try:
            if not self.api.direct_connect(config.HOST, config.PORT):
                raise ConnectionError(f"Failed to connect to {config.HOST}:{config.PORT}")
            self.device = self.api.get_device()
            return self.device
        except Exception as e:
            print(f"Connection Error: {e}", file=sys.stderr)
            sys.exit(1)

    def fetch_stats(self):
        try:
            state = self.device.downloadcontroller.get_current_state()

            links = self.device.downloads.query_links([TUI_LINK_STATE_QUERY.copy()])

            running_links = []
            enabled_unfinished_links = []

            for link in links:
                if link.get("finished"):
                    continue

                if link.get("running"):
                    running_links.append(link)
                elif link.get("enabled"):
                    enabled_unfinished_links.append(link)

            return state, running_links, enabled_unfinished_links
        except Exception:
            return "ERROR", [], []

    def toggle_state(self, current_state):
        if current_state in ["RUNNING", "DOWNLOADING"]:
            self.device.downloadcontroller.stop_downloads()
        else:
            self.device.downloadcontroller.start_downloads()
