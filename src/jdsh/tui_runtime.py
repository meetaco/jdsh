"""Dashboard state and scheduling, independent of Rich and terminal input."""

import logging
from dataclasses import dataclass
from typing import List, Optional

from .errors import ServiceError


OPERATION_ERROR_SECONDS = 5.0
MIN_REFRESH_SECONDS = 0.1
INPUT_POLL_SECONDS = 0.1


@dataclass(frozen=True)
class Snapshot:
    """Retain raw list/dict references without mutating them; frozen is shallow."""

    state: str
    running_links: List[dict]
    enabled_unfinished_links: List[dict]
    error: Optional[str] = None
    last_success_at: Optional[float] = None
    consecutive_failures: int = 0


def refresh_status(snapshot, now):
    """Describe poll health using monotonic elapsed time, not download state."""
    if snapshot.last_success_at is None:
        updated = "No successful refresh yet"
    else:
        age = max(0, int(now - snapshot.last_success_at))
        updated = f"Last success: {age}s ago"
    if snapshot.error is not None:
        count = snapshot.consecutive_failures
        failures = "failure" if count == 1 else "failures"
        return f"Retrying ({count} {failures}) | {updated}"
    if snapshot.last_success_at is None:
        return f"Connecting | {updated}"
    return f"Live | {updated}"


def poll_stats(client):
    try:
        state, running, unfinished = client.fetch_stats()
        return state, running, unfinished, None
    except ServiceError as e:
        logging.getLogger(__name__).debug("Polling failed", exc_info=True)
        return "ERROR", [], [], f"ERROR: {e}"


class DashboardController:
    """Keep the last poll and the operation error's independent lifetime."""

    def __init__(self, client, clock):
        self.client = client
        self.clock = clock
        self.snapshot = Snapshot("UNKNOWN", [], [])
        self.operation_error = None
        self.operation_error_expires = 0.0

    def poll(self):
        state, running, unfinished, error = poll_stats(self.client)
        previous = self.snapshot
        # Timestamp completion: a slow request must not make a fresh result old.
        last_success = self.clock() if error is None else previous.last_success_at
        self.snapshot = Snapshot(
            state=state, running_links=running,
            enabled_unfinished_links=unfinished, error=error,
            last_success_at=last_success,
            consecutive_failures=previous.consecutive_failures + 1 if error is not None else 0,
        )

    def expire_error(self, now):
        """Use a sample from the injected clock, reusing the loop start time."""
        if now >= self.operation_error_expires:
            self.operation_error = None

    @property
    def can_toggle(self):
        return self.snapshot.state != "ERROR"

    @property
    def can_navigate(self):
        return self.snapshot.error is None and self.snapshot.state not in ("CONNECTING...", "ERROR")

    @property
    def toggle_feedback(self):
        return "STOPPING..." if self.snapshot.state in ("RUNNING", "DOWNLOADING") else "STARTING..."

    @property
    def display_error(self):
        # A failed poll takes precedence; the operation error can reappear on recovery.
        return self.snapshot.error or self.operation_error

    def toggle(self):
        """Ignore control while polling is unavailable, including direct callers."""
        if not self.can_toggle:
            return
        try:
            self.client.toggle_state(self.snapshot.state)
            self.operation_error = None
        except ServiceError as e:
            logging.getLogger(__name__).debug("Download control failed", exc_info=True)
            self.operation_error = f"ERROR: {e}"
            self.operation_error_expires = self.clock() + OPERATION_ERROR_SECONDS


def run_loop(client, *, get_key, render, clock, sleep, handle_key=None, on_idle=None, handle_view_key=None):
    """Run until interrupted, using injected input, rendering and monotonic time."""
    controller = DashboardController(client, clock)
    render(Snapshot("CONNECTING...", [], []), "LOADING...")
    controller.poll()
    render(controller.snapshot, controller.display_error)

    while True:
        start_time = clock()
        controller.expire_error(start_time)
        while clock() - start_time < max(client.settings.refresh_rate, MIN_REFRESH_SECONDS):
            if on_idle is not None:
                on_idle(controller.snapshot, controller.display_error)
            key = get_key()
            if handle_view_key is not None and handle_view_key(key, controller.snapshot):
                render(controller.snapshot, controller.display_error)
                continue
            if key == "s" and controller.can_toggle:
                render(controller.snapshot, controller.toggle_feedback)
                controller.toggle()
                if controller.operation_error:
                    render(controller.snapshot, controller.operation_error)
                break
            navigated = handle_key is not None and controller.can_navigate and handle_key(key)
            if navigated:
                render(controller.snapshot, controller.display_error)
            # Drain buffered key repeats promptly; polling still has its deadline.
            if not navigated:
                sleep(INPUT_POLL_SECONDS)

        controller.poll()
        controller.expire_error(clock())
        render(controller.snapshot, controller.display_error)
