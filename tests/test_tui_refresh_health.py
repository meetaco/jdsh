"""Poll freshness and retry feedback without JD or a terminal session."""

import io
import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.cells import cell_len
from rich.console import Console

from jdsh import tui
from jdsh.errors import ServiceError, StatsError
from jdsh.tui_navigation import Navigation
from jdsh.tui_runtime import DashboardController, Snapshot, refresh_status


class RefreshHealthTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.client = MagicMock()
        self.client.fetch_stats.return_value = ('STOPPED', [], [])
        self.controller = DashboardController(self.client, lambda: self.now)

    def test_startup_failures_never_claim_a_successful_refresh(self):
        self.assertEqual(refresh_status(self.controller.snapshot, 0),
                         'Connecting | No successful refresh yet')
        self.client.fetch_stats.side_effect = StatsError('offline')
        for count in (1, 2):
            self.controller.poll()
            self.assertIsNone(self.controller.snapshot.last_success_at)
            self.assertEqual(self.controller.snapshot.consecutive_failures, count)
            self.assertIn('Retrying', refresh_status(self.controller.snapshot, 10))
            self.assertIn('No successful refresh yet', refresh_status(self.controller.snapshot, 10))
            self.assertFalse(self.controller.can_toggle)
            self.assertFalse(self.controller.can_navigate)

    def test_failed_polls_keep_success_time_and_recovery_resets_count(self):
        self.controller.poll()  # A timestamp of zero is a real success.
        self.client.fetch_stats.side_effect = [StatsError('offline'), StatsError('offline'),
                                               ('RUNNING', [], [])]
        self.now = 5.0
        self.controller.poll()
        self.assertEqual(refresh_status(self.controller.snapshot, 5.9),
                         'Retrying (1 failure) | Last success: 5s ago')
        self.now = 10.0
        self.controller.poll()
        self.assertEqual(refresh_status(self.controller.snapshot, 12),
                         'Retrying (2 failures) | Last success: 12s ago')
        self.assertEqual(self.controller.snapshot.running_links, [])
        self.now = 15.0
        self.controller.poll()
        self.assertEqual(self.controller.snapshot.last_success_at, 15)
        self.assertEqual(self.controller.snapshot.consecutive_failures, 0)
        self.assertIsNone(self.controller.display_error)
        self.assertEqual(refresh_status(self.controller.snapshot, 16),
                         'Live | Last success: 1s ago')
        self.assertTrue(self.controller.can_toggle)

    def test_success_time_is_sampled_after_slow_fetch(self):
        def fetch():
            self.now = 30.0
            return 'STOPPED', [], []
        self.client.fetch_stats.side_effect = fetch
        self.controller.poll()
        self.assertEqual(self.controller.snapshot.last_success_at, 30)
        self.assertIn('0s ago', refresh_status(self.controller.snapshot, 30))

    def test_control_failure_does_not_count_as_poll_failure(self):
        self.controller.poll()
        self.client.toggle_state.side_effect = ServiceError('denied')
        self.now = 3
        self.controller.toggle()
        self.assertEqual(self.controller.display_error, 'ERROR: denied')
        self.assertEqual(self.controller.snapshot.consecutive_failures, 0)
        self.assertEqual(refresh_status(self.controller.snapshot, 3),
                         'Live | Last success: 3s ago')
        self.assertTrue(self.controller.can_navigate)

    def test_poll_failure_outlives_operation_error_deadline(self):
        self.controller.poll()
        self.client.toggle_state.side_effect = ServiceError('denied')
        self.controller.toggle()
        self.client.fetch_stats.side_effect = StatsError('offline')
        self.controller.poll()
        self.controller.expire_error(100)
        self.assertIsNone(self.controller.operation_error)
        self.assertEqual(self.controller.snapshot.error, 'ERROR: offline')
        self.assertEqual(refresh_status(self.controller.snapshot, 100),
                         'Retrying (1 failure) | Last success: 100s ago')

    def test_successful_toggle_keeps_health_until_next_poll(self):
        self.controller.poll()
        previous = self.controller.snapshot
        self.now = 10
        self.controller.toggle()
        self.client.toggle_state.assert_called_once_with('STOPPED')
        self.assertIs(self.controller.snapshot, previous)
        self.assertEqual(refresh_status(self.controller.snapshot, 10),
                         'Live | Last success: 10s ago')
        self.controller.poll()
        self.assertEqual(self.controller.snapshot.last_success_at, 10)
        self.assertEqual(self.controller.snapshot.consecutive_failures, 0)

    def test_default_run_clock_is_monotonic(self):
        keyboard, live, console = MagicMock(), MagicMock(), MagicMock()
        clock = MagicMock(return_value=0)
        with patch.object(tui, 'Live', return_value=live), \
             patch.object(tui.time, 'monotonic', clock), \
             patch.object(tui, 'run_loop') as run_loop:
            tui.run(self.client, console=console, keyboard=keyboard)
        self.assertIs(run_loop.call_args.kwargs['clock'], clock)

    def test_age_is_nonnegative_and_does_not_depend_on_wall_time(self):
        snapshot = Snapshot('STOPPED', [], [], last_success_at=100)
        self.assertIn('0s ago', refresh_status(snapshot, 99))
        self.assertIn('86400s ago', refresh_status(snapshot, 86500))

    def test_80_column_error_header_keeps_viewport_and_saved_selection(self):
        nav = Navigation()
        nav.sync([{'uuid': 1, 'name': '日本語のファイル'}], [])
        snapshot = Snapshot('ERROR', [], [], error='ERROR: offline',
                            last_success_at=0, consecutive_failures=2)
        output = io.StringIO()
        Console(file=output, width=80, height=18).print(tui.generate_layout(
            snapshot.state, [], [], snapshot.error, navigation=nav, width=80, height=18,
            refresh_status=refresh_status(snapshot, 12)))
        text = output.getvalue()
        self.assertIn('Retrying (2 failures)', text)
        self.assertIn('Last success: 12s ago', text)
        self.assertIn('ERROR: offline', text)
        self.assertIn('Selected ID: -', text)
        self.assertEqual(nav.selected_id, 1)
        self.assertEqual(len(text.rstrip('\n').splitlines()), 18)
        self.assertTrue(all(cell_len(line) <= 80 for line in text.splitlines()))

    def test_age_redraws_between_polls_without_extra_fetch_or_key(self):
        console = Console(file=io.StringIO(), width=80, height=18)
        self.client.settings = SimpleNamespace(refresh_rate=60)
        live, keyboard = MagicMock(), MagicMock()
        live.__enter__.return_value = live
        calls = [0]
        def get_key():
            calls[0] += 1
            if self.now >= 2.1:
                raise KeyboardInterrupt
            return None
        keyboard.__enter__.return_value.get_key.side_effect = get_key
        def sleep(value):
            self.now += value
        with patch.object(tui, 'Live', return_value=live), patch.object(console, 'clear'):
            tui.run(self.client, console=console, keyboard=keyboard,
                    clock=lambda: self.now, sleep=sleep)
        self.client.fetch_stats.assert_called_once()
        self.client.toggle_state.assert_not_called()
        output = io.StringIO()
        Console(file=output, width=80, height=18).print(live.update.call_args.args[0])
        self.assertIn('Live | Last success: 2s ago', output.getvalue())
        live.__exit__.assert_called_once()
        keyboard.__exit__.assert_called_once()

    def test_real_live_refresh_advances_age_during_blocked_fetch(self):
        observed_age = threading.Event()
        in_fetch = [False]
        class RecordingOutput(io.StringIO):
            def write(stream, value):
                result = super().write(value)
                if in_fetch[0] and 'Last success: 10s ago' in value:
                    observed_age.set()
                return result
        output = RecordingOutput()
        console = Console(file=output, force_terminal=True, force_interactive=True,
                          color_system=None, width=80, height=18)
        self.client.settings = SimpleNamespace(refresh_rate=0.1)
        observed_before_return = []
        def slow_fetch():
            if self.client.fetch_stats.call_count == 1:
                return 'STOPPED', [], []
            in_fetch[0] = True
            self.now = 10
            # The real Rich refresh thread must render while this call is blocked.
            observed_before_return.append(observed_age.wait(timeout=3))
            in_fetch[0] = False
            return 'STOPPED', [], []
        self.client.fetch_stats.side_effect = slow_fetch
        keyboard = MagicMock()
        def get_key():
            if self.client.fetch_stats.call_count >= 2:
                raise KeyboardInterrupt
            return None
        keyboard.__enter__.return_value.get_key.side_effect = get_key
        def sleep(value):
            self.now += value
        # CI shells may expose TERM=dumb even with force_terminal=True.
        with patch.dict(os.environ, {'TERM': 'xterm'}):
            tui.run(self.client, console=console, keyboard=keyboard,
                    clock=lambda: self.now, sleep=sleep)
        self.assertEqual(observed_before_return, [True])
        self.assertEqual(self.client.fetch_stats.call_count, 2)
        self.client.toggle_state.assert_not_called()
        keyboard.__exit__.assert_called_once()

    def test_refresh_header_samples_clock_once_and_does_not_mutate_navigation(self):
        nav = Navigation()
        nav.sync([{'uuid': 1, 'name': 'file', 'running': True}], [])
        snapshot = Snapshot('RUNNING', nav.rows[0], [], last_success_at=0)
        clock = MagicMock(return_value=2)
        layout = tui.generate_layout('RUNNING', snapshot.running_links, [],
                                     navigation=nav, refresh_snapshot=snapshot,
                                     refresh_clock=clock)
        before = (nav.selected_id, nav.indices[:], nav.offsets[:], nav.capacity[:])
        output = io.StringIO()
        console = Console(file=output, width=100, height=25)
        console.print(layout)
        clock.assert_called_once_with()
        self.assertIn('Last success: 2s ago', output.getvalue())
        self.assertEqual(before, (nav.selected_id, nav.indices, nav.offsets, nav.capacity))


if __name__ == '__main__':
    unittest.main()
