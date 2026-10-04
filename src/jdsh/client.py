from types import MappingProxyType

from myjdapi import Myjdapi
from . import config
from .stats import partition_links
from .errors import JDConnectionError, ServiceError, StatsError


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

# The ordinary list view needs enough state to answer the common operational
# question "why is this link not downloading?" without paying for URL/date fields.
LIST_LINK_STATE_QUERY = {
    **COMPACT_LINK_STATE_QUERY,
    "advancedStatus": True,
    "extractionStatus": True,
    "host": True,
    "priority": True,
}

# Keep diagnostic output broad, but deliberately omit the upstream `password`
# field so `jd ls -d` and `jd show --json` do not expose download credentials.
DOWNLOAD_LINK_STATE_QUERY = {
    **LIST_LINK_STATE_QUERY,
    "speed": True,
    "eta": True,
    "url": True,
    "addedDate": True,
    "comment": True,
    "finishedDate": True,
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

# Static status needs completion flags, without the TUI's queued-link selection.
STATUS_LINK_STATE_QUERY = MappingProxyType({
    "name": True,
    "bytesLoaded": True,
    "bytesTotal": True,
    "speed": True,
    "running": True,
    "eta": True,
    "status": True,
    "finished": True,
})

GRABBER_LINK_STATE_QUERY = MappingProxyType({
    "name": True,
    "uuid": True,
    "url": True,
})

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
    def __init__(self, settings=None, api=None):
        self.settings = config.Settings() if settings is None else settings
        self.api = Myjdapi() if api is None else api
        self.api.set_app_key(config.APP_KEY)
        self.device = None

    def connect(self):
        try:
            if not self.api.direct_connect(self.settings.host, self.settings.port):
                raise ConnectionError("direct connection was not established")
            self.device = self.api.get_device()
            return self.device
        except Exception as e:
            raise JDConnectionError(f"Failed to connect to {self.settings.host}:{self.settings.port}: {e}") from e

    def fetch_stats(self):
        try:
            state = self.device.downloadcontroller.get_current_state()

            links = self.device.downloads.query_links([TUI_LINK_STATE_QUERY.copy()])

            running_links, enabled_unfinished_links = partition_links(links)

            return state, running_links, enabled_unfinished_links
        except Exception as e:
            raise StatsError(f"Failed to fetch download status: {e}") from e

    def toggle_state(self, current_state):
        action = "stop" if current_state in ["RUNNING", "DOWNLOADING"] else "start"
        try:
            if action == "stop":
                self.device.downloadcontroller.stop_downloads()
            else:
                self.device.downloadcontroller.start_downloads()
        except Exception as e:
            raise ServiceError(f"Failed to {action} downloads: {e}") from e
