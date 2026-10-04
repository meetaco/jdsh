"""Compare TUI rendering/control/poll order with a trusted pre-refactor git ref."""

import argparse
import subprocess
import types
from unittest.mock import MagicMock, patch

from jdsh import tui
from jdsh.errors import ServiceError, StatsError


def trace(module, state, rate, poll_failures=(), toggle_failures=()):
    events = []
    client = MagicMock()
    client.settings.refresh_rate = rate
    now = [0.0]
    state_now = [state]
    keys = iter(["x", "s", 1.0, "s", 3.0, 6.0])

    def poll():
        events.append(("poll", client.fetch_stats.call_count))
        if client.fetch_stats.call_count in poll_failures:
            raise StatsError("offline")
        return state_now[0], [{"name": "running"}], [{"name": "waiting"}]

    def toggle(current):
        events.append(("toggle", current))
        if client.toggle_state.call_count in toggle_failures:
            raise ServiceError("denied")
        state_now[0] = "STOPPED" if current in ("RUNNING", "DOWNLOADING") else "RUNNING"

    def key():
        try:
            value = next(keys)
        except StopIteration:
            raise KeyboardInterrupt
        if isinstance(value, float):
            now[0] = value
            return None
        return value

    def sleep(seconds):
        events.append(("sleep", seconds))
        now[0] += seconds

    def render(state, running, waiting, override_status=None):
        events.append(("render", state, running, waiting, override_status))
        return None

    client.fetch_stats.side_effect = poll
    client.toggle_state.side_effect = toggle
    with patch.object(module, "Console"), patch.object(module, "Live"), \
         patch.object(module, "KeyboardInput") as keyboard, \
         patch.object(module, "generate_layout", side_effect=render), \
         patch.object(module.time, "monotonic", side_effect=lambda: now[0]), \
         patch.object(module.time, "sleep", side_effect=sleep):
        keyboard.return_value.__enter__.return_value.get_key.side_effect = key
        module.run(client)
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="451684e", help="Trusted local pre-refactor git ref")
    args = parser.parse_args()
    baseline = types.ModuleType("jdsh._baseline_tui")
    baseline.__package__ = "jdsh"
    source = subprocess.check_output(["git", "show", f"{args.baseline}:src/jdsh/tui.py"], text=True)
    exec(compile(source, "baseline_tui.py", "exec"), baseline.__dict__)
    count = 0
    for state in ("STOPPED", "RUNNING", "DOWNLOADING"):
        for rate in (0.25, 0.5, 1e-9):
            for polls, toggles in (((), ()), ((1, 3), ()), ((), (1, 2)), ((3,), (1,))):
                previous = trace(baseline, state, rate, polls, toggles)
                current = trace(tui, state, rate, polls, toggles)
                if previous != current:
                    raise AssertionError((state, rate, polls, toggles, previous, current))
                count += 1
    print(f"{count} TUI render/control/poll/sleep comparisons passed.")


if __name__ == "__main__":
    main()
