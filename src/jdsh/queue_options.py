"""Queue browsing choices without service or diagnostic dependencies."""

LINK_STATES = ("RUNNING", "FINISHED", "DISABLED", "PROCESSING", "WAITING",
               "SKIPPED", "FINAL", "OFFLINE", "STATUS", "UNKNOWN")
SORT_KEYS = ("name", "id", "host", "size", "progress", "finished")
