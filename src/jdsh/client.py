import sys
from myjdapi import Myjdapi
from . import config


DOWNLOAD_LINK_STATE_QUERY = {
    "name": True,
    "bytesLoaded": True,
    "bytesTotal": True,
    "speed": True,
    "running": True,
    "eta": True,
    "status": True,
    "advancedStatus": True,
    "finished": True,
    "enabled": True,
    "skipped": True,
    "extractionStatus": True,
    "host": True,
    "uuid": True,
    "url": True,
}

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
