import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.cells import cell_len
from rich.console import Console

from jdsh import services, tui
from jdsh.errors import StatsError
from jdsh.tui_details import Details
from jdsh.tui_navigation import Navigation


def link(link_id=1):
    return {'uuid': link_id, 'name': '[red]日本語の名前[/red]', 'enabled': True,
            'finished': False, 'running': False, 'status': None,
            'advancedStatus': {'ConditionalSkipReason': {'label': 'Wait before retry'},
                               'AvailableStatus': {'id': 'TRUE', 'label': 'Online'}}}


class DetailsTests(unittest.TestCase):
    def device(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [link()]
        device.downloadcontroller.get_current_state.return_value = 'RUNNING'
        return device

    def test_fetch_uses_cli_diagnosis_and_keeps_credentials_out(self):
        device, details = self.device(), Details()
        details.fetch(device, 1)
        self.assertEqual(details.payload, services.explain_download(device, 1))
        self.assertEqual(details.payload['diagnosis']['source'], 'jdownloader')
        query = device.downloads.query_links.call_args.args[0][0]
        self.assertEqual(query['linkUUIDs'], [1])
        self.assertNotIn('password', query)
        self.assertNotIn('url', details.payload)
        device.downloads.query_packages.assert_not_called()
        device.action.assert_not_called()

    def test_missing_link_and_refresh_failure_clear_old_payload(self):
        device, details = self.device(), Details()
        details.fetch(device, 1)
        device.downloads.query_links.return_value = []
        details.fetch(device, 1)
        self.assertIsNone(details.payload)
        self.assertIn('not found: 1', details.error)
        device.downloads.query_links.side_effect = RuntimeError('offline')
        details.fetch(device, 1)
        self.assertIn('Failed to query', details.error)
        details.close()
        self.assertFalse(details.is_open)
        self.assertIsNone(details.error)

    def test_long_literal_diagnosis_scrolls_and_resizes_at_80_by_18(self):
        device, details = self.device(), Details()
        device.downloads.query_links.return_value[0]['advancedStatus']['ConditionalSkipReason']['label'] = ('日本語の長い理由 [blue]literal[/blue] ' * 30) + 'LAST-REASON'
        details.fetch(device, 1)
        nav = Navigation()
        nav.sync([], [link()])
        output = io.StringIO()
        Console(file=output, width=80, height=18).print(tui.generate_layout(
            'RUNNING', [], [link()], navigation=nav, width=80, height=18, details=details))
        self.assertIn('[red]', output.getvalue())
        self.assertIn('Source: jdownloader', output.getvalue())
        self.assertGreater(len(details.lines), details.capacity)
        details.scroll('end')
        output = io.StringIO()
        Console(file=output, width=80, height=18).print(tui.generate_layout(
            'RUNNING', [], [link()], navigation=nav, width=80, height=18, details=details))
        self.assertIn('LAST-REASON', output.getvalue())
        self.assertEqual(len(output.getvalue().rstrip('\n').splitlines()), 18)
        self.assertTrue(all(cell_len(line) <= 80 for line in output.getvalue().splitlines()))
        details.panel(100, 34)
        self.assertLessEqual(details.offset, max(0, len(details.lines) - details.capacity))
        details.scroll('home')
        self.assertEqual(details.offset, 0)
        details.scroll('pageup')
        self.assertEqual(details.offset, 0)

    def test_poll_failure_labels_captured_details_and_keeps_selection(self):
        details = Details()
        details.fetch(self.device(), 1)
        nav = Navigation()
        nav.sync([], [link()])
        output = io.StringIO()
        Console(file=output, width=100, height=25).print(tui.generate_layout(
            'ERROR', [], [], 'ERROR: offline', navigation=nav, details=details))
        self.assertIn('captured details may be stale', output.getvalue())
        self.assertIn('Details ID: 1', output.getvalue())
        self.assertEqual(nav.selected_id, 1)

    def run_keys(self, keys, snapshots):
        client = MagicMock()
        client.settings = SimpleNamespace(refresh_rate=0.1)
        client.device = self.device()
        client.fetch_stats.side_effect = snapshots
        live, keyboard = MagicMock(), MagicMock()
        live.__enter__.return_value = live
        events = iter(keys)
        def get_key():
            try:
                return next(events)
            except StopIteration:
                raise KeyboardInterrupt
        keyboard.__enter__.return_value.get_key.side_effect = get_key
        now = [0.0]
        console = Console(file=io.StringIO(), width=80, height=18)
        with patch.object(tui, 'Live', return_value=live), patch.object(console, 'clear'):
            tui.run(client, console=console, keyboard=keyboard, clock=lambda: now[0],
                    sleep=lambda value: now.__setitem__(0, now[0] + value))
        return client, live

    def test_d_fetches_once_and_scrolling_does_not_poll_or_mutate(self):
        client, live = self.run_keys(['d', 'j', 'end', 'home', '\t', 'q'], [('RUNNING', [], [link()])])
        client.device.downloads.query_links.assert_called_once()
        client.fetch_stats.assert_called_once()
        client.toggle_state.assert_not_called()
        output = io.StringIO()
        Console(file=output, width=80, height=18).print(live.update.call_args.args[0])
        self.assertIn('Selected ID: 1', output.getvalue())
        self.assertNotIn('Link details / diagnosis', output.getvalue())

    def test_s_in_details_still_controls_global_controller(self):
        client, live = self.run_keys(['d', 's'],
                                    [('RUNNING', [], [link()]), ('STOPPED', [], [link()])])
        client.toggle_state.assert_called_once_with('RUNNING')
        client.device.downloads.query_links.assert_called_once()
        self.assertEqual(client.fetch_stats.call_count, 2)
        output = io.StringIO()
        Console(file=output, width=80, height=18).print(live.update.call_args.args[0])
        self.assertIn('Details ID: 1', output.getvalue())

    def test_d_on_empty_or_failed_snapshot_never_queries_details(self):
        for snapshot in [('RUNNING', [], []), StatsError('offline')]:
            client, live = self.run_keys(['d'], [snapshot])
            client.device.downloads.query_links.assert_not_called()
            client.toggle_state.assert_not_called()

    def test_details_stay_pinned_when_selected_link_disappears(self):
        client, live = self.run_keys(['d', None, 'd', 'q'],
                                    [('RUNNING', [], [link()]), ('RUNNING', [], [link(2)])])
        self.assertEqual(client.device.downloads.query_links.call_count, 2)
        for call in client.device.downloads.query_links.call_args_list:
            self.assertEqual(call.args[0][0]['linkUUIDs'], [1])
        output = io.StringIO()
        Console(file=output, width=80, height=18).print(live.update.call_args.args[0])
        self.assertIn('Selected ID: 2', output.getvalue())

    def test_q_closes_during_failed_poll_and_d_does_not_retry_details(self):
        client, live = self.run_keys(['d', None, 'd', 'q'],
                                    [('RUNNING', [], [link()]), StatsError('offline')])
        client.device.downloads.query_links.assert_called_once()
        output = io.StringIO()
        Console(file=output, width=80, height=18).print(live.update.call_args.args[0])
        self.assertIn('ERROR: offline', output.getvalue())
        self.assertNotIn('Link details / diagnosis', output.getvalue())


if __name__ == '__main__':
    unittest.main()
