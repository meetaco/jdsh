"""Exercise time and input without terminal setup or patching global clocks."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jdsh import tui
from jdsh.errors import ServiceError, StatsError
from jdsh.tui_runtime import DashboardController, run_loop


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.pauses = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.pauses.append(seconds)
        self.now += seconds


def make_client(refresh_rate=0.5):
    client = MagicMock()
    client.settings = SimpleNamespace(refresh_rate=refresh_rate)
    client.fetch_stats.return_value = ("STOPPED", [], [])
    return client


class DashboardControllerTests(unittest.TestCase):
    def setUp(self):
        self.time = FakeTime()
        self.client = make_client()
        self.controller = DashboardController(self.client, self.time.clock)
        self.controller.poll()

    def test_raw_lists_are_retained_by_snapshot(self):
        running, waiting = [{"name": "running"}], [{"name": "waiting"}]
        self.client.fetch_stats.return_value = ("DOWNLOADING", running, waiting)
        self.controller.poll()
        self.assertIs(self.controller.snapshot.running_links, running)
        self.assertIs(self.controller.snapshot.enabled_unfinished_links, waiting)
        self.assertEqual(self.controller.toggle_feedback, "STOPPING...")
        self.controller.toggle()
        self.client.toggle_state.assert_called_once_with("DOWNLOADING")

    def test_poll_failure_blocks_toggle_and_recovery_enables_it(self):
        self.client.fetch_stats.side_effect = [StatsError("offline"), ("STOPPED", [], [])]
        self.controller.poll()
        self.assertFalse(self.controller.can_toggle)
        self.controller.toggle()
        self.client.toggle_state.assert_not_called()
        self.assertEqual(self.controller.display_error, "ERROR: offline")
        self.controller.poll()
        self.assertTrue(self.controller.can_toggle)
        self.assertIsNone(self.controller.display_error)
        self.assertEqual(self.controller.toggle_feedback, "STARTING...")

    def test_operation_error_survives_polls_and_expires_at_exact_deadline(self):
        self.client.toggle_state.side_effect = ServiceError("denied")
        self.controller.toggle()
        for now in (1.0, 3.0, 4.999):
            self.controller.poll()
            self.controller.expire_error(now)
            self.assertEqual(self.controller.display_error, "ERROR: denied")
        self.controller.expire_error(5.0)
        self.assertIsNone(self.controller.display_error)

    def test_poll_error_takes_precedence_without_resetting_operation_deadline(self):
        self.client.toggle_state.side_effect = ServiceError("denied")
        self.controller.toggle()
        self.client.fetch_stats.side_effect = [StatsError("offline"), ("STOPPED", [], [])]
        self.controller.poll()
        self.controller.expire_error(1.0)
        self.assertEqual(self.controller.display_error, "ERROR: offline")
        self.controller.poll()
        self.controller.expire_error(2.0)
        self.assertEqual(self.controller.display_error, "ERROR: denied")
        self.controller.expire_error(5.0)
        self.assertIsNone(self.controller.display_error)

    def test_repeated_failure_renews_deadline_and_success_clears_error(self):
        self.client.toggle_state.side_effect = [ServiceError("first"), ServiceError("second"), None]
        self.controller.toggle()
        self.time.now = 2.0
        self.controller.toggle()
        self.controller.expire_error(5.0)
        self.assertEqual(self.controller.display_error, "ERROR: second")
        self.controller.toggle()
        self.assertIsNone(self.controller.display_error)

    def test_unexpected_sdk_failure_is_not_hidden(self):
        self.client.toggle_state.side_effect = RuntimeError("unexpected")
        with self.assertRaisesRegex(RuntimeError, "unexpected"):
            self.controller.toggle()


class RuntimeLoopTests(unittest.TestCase):
    def test_custom_and_minimum_refresh_intervals(self):
        for rate, expected_pauses in ((0.25, 3), (1e-9, 1)):
            with self.subTest(rate=rate):
                timer, client, views = FakeTime(), make_client(rate), []

                def get_key():
                    if client.fetch_stats.call_count > 1:
                        raise KeyboardInterrupt
                    return None

                with self.assertRaises(KeyboardInterrupt):
                    run_loop(client, get_key=get_key, render=lambda *view: views.append(view),
                             clock=timer.clock, sleep=timer.sleep)
                self.assertEqual(timer.pauses, [0.1] * expected_pauses)
                self.assertEqual(client.fetch_stats.call_count, 2)
                self.assertEqual(views[0][0].state, "CONNECTING...")
                self.assertEqual(views[0][1], "LOADING...")
                self.assertEqual(views[1][0].state, "STOPPED")

    def test_toggle_feedback_precedes_operation_and_poll_follows_immediately(self):
        timer, client, events = FakeTime(), make_client(), []
        keys = iter(["s", "s"])
        client.fetch_stats.side_effect = [("STOPPED", [], []), ("RUNNING", [], []), ("STOPPED", [], [])]
        client.toggle_state.side_effect = lambda state: events.append(("toggle", state))

        def get_key():
            try:
                return next(keys)
            except StopIteration:
                raise KeyboardInterrupt

        def render(snapshot, override):
            events.append(("render", snapshot.state, override))

        with self.assertRaises(KeyboardInterrupt):
            run_loop(client, get_key=get_key, render=render, clock=timer.clock, sleep=timer.sleep)
        self.assertEqual(events, [
            ("render", "CONNECTING...", "LOADING..."), ("render", "STOPPED", None),
            ("render", "STOPPED", "STARTING..."), ("toggle", "STOPPED"),
            ("render", "RUNNING", None), ("render", "RUNNING", "STOPPING..."),
            ("toggle", "RUNNING"), ("render", "STOPPED", None),
        ])
        self.assertEqual(timer.pauses, [])

    def test_s_is_ignored_during_poll_error_until_recovery(self):
        timer, client, views = FakeTime(), make_client(0.1), []
        client.fetch_stats.side_effect = [StatsError("offline"), ("STOPPED", [], []), ("RUNNING", [], [])]
        keys = iter(["s", "s"])

        def get_key():
            try:
                return next(keys)
            except StopIteration:
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            run_loop(client, get_key=get_key, render=lambda *view: views.append(view),
                     clock=timer.clock, sleep=timer.sleep)
        client.toggle_state.assert_called_once_with("STOPPED")
        self.assertEqual(timer.pauses, [0.1])
        self.assertEqual(views[1][1], "ERROR: offline")
        self.assertEqual(views[-1][0].state, "RUNNING")


class TerminalLifecycleTests(unittest.TestCase):
    def test_injected_keyboard_and_live_are_closed_on_interrupt_or_failure(self):
        for error in (KeyboardInterrupt(), RuntimeError("unexpected")):
            with self.subTest(error=type(error).__name__):
                keyboard, live, console = MagicMock(), MagicMock(), MagicMock()
                exits = []
                live.__exit__.side_effect = lambda *args: exits.append("live") or False
                keyboard.__exit__.side_effect = lambda *args: exits.append("keyboard") or False
                keyboard.__enter__.return_value.get_key.side_effect = error
                timer, client = FakeTime(), make_client()
                with patch.object(tui, "KeyboardInput", side_effect=AssertionError("use injected input")), \
                     patch.object(tui, "Live", return_value=live) as factory:
                    if isinstance(error, KeyboardInterrupt):
                        tui.run(client, console=console, keyboard=keyboard,
                                clock=timer.clock, sleep=timer.sleep)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "unexpected"):
                            tui.run(client, console=console, keyboard=keyboard,
                                    clock=timer.clock, sleep=timer.sleep)
                self.assertEqual(exits, ["live", "keyboard"])
                keyboard.__exit__.assert_called_once()
                live.__exit__.assert_called_once()
                console.clear.assert_called_once()
                factory.assert_called_once_with(console=console, refresh_per_second=4, screen=True)
