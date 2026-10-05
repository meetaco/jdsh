import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.cells import cell_len
from rich.console import Console

from jdsh import services, tui
from jdsh.errors import StatsError
from jdsh.tui_details import Details, display_text
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

    def run_keys(self, keys, snapshots, query_observer=None):
        client = MagicMock()
        client.settings = SimpleNamespace(refresh_rate=0.1)
        client.device = self.device()
        client.fetch_stats.side_effect = snapshots
        live, keyboard = MagicMock(), MagicMock()
        live.__enter__.return_value = live
        if query_observer is not None:
            client.device.downloads.query_links.side_effect = lambda *args: query_observer(live) or [link()]
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

    def test_newlines_preserved_controls_neutralized_and_no_trailing_blank(self):
        details, device = Details(), self.device()
        device.downloads.query_links.return_value[0]['name'] = '[red]line 1\nline 2[/red]'
        device.downloads.query_links.return_value[0]['status'] = '\x1b[31mstatus\x1b]0;title\x07\x9b\x00'
        details.fetch(device, 1)
        panel = details.panel(100, 34)
        text = '\n'.join(line.plain for line in details.lines)
        self.assertIn('[red]line 1\nline 2[/red]', text)
        self.assertNotIn('\x1b', text)
        self.assertNotIn('\x9b', text)
        self.assertNotIn('\x00', text)
        self.assertIn('?[31mstatus?', text)
        self.assertTrue(details.lines[-1].plain)
        self.assertEqual(display_text('a\r\nb\rc\td'), 'a\nb\nc?d')

    def test_close_resets_viewport_and_reuses_supplied_console(self):
        from jdsh import tui_details
        console = Console(file=io.StringIO(), width=80)
        with patch.object(tui_details, 'Console', side_effect=AssertionError('reuse supplied console')):
            details = Details(console)
            details.fetch(self.device(), 1)
            details.panel(80, 12)
            details.scroll('end')
            details.panel(100, 20)
            details.close()
        self.assertEqual((details.offset, details.lines, details.capacity), (0, [], 1))
        self.assertIn('Lines: 0-0/0', details.footer().plain)

    def test_missing_or_invalid_diagnosis_does_not_crash_display(self):
        for diagnosis in (None, [], 'unexpected'):
            details = Details()
            details.link_id = 1
            details.payload = {'name': 'file', 'diagnosis': diagnosis}
            details.panel(80, 12)
            self.assertIn('Diagnosis: not provided', '\n'.join(line.plain for line in details.lines))
        details.payload.pop('diagnosis')
        details.panel(80, 12)

    def test_controller_query_failure_remains_nonfatal_and_unknown(self):
        device, details = self.device(), Details()
        device.downloadcontroller.get_current_state.side_effect = RuntimeError('offline')
        details.fetch(device, 1)
        self.assertIsNone(details.error)
        self.assertIsNone(details.payload['controllerState'])
        self.assertEqual(details.payload['diagnosis']['source'], 'jdownloader')

    def test_loading_frame_is_refreshed_before_query(self):
        observed = []
        def observe(live):
            call = live.update.call_args
            self.assertTrue(call.kwargs['refresh'])
            output = io.StringIO()
            Console(file=output, width=80, height=18).print(call.args[0])
            observed.append(output.getvalue())
        client, live = self.run_keys(['d'], [('RUNNING', [], [link()])], observe)
        self.assertIn('Loading details', observed[0])
        client.device.downloads.query_links.assert_called_once()

    def test_tab_with_both_panes_keeps_queue_selection(self):
        client, live = self.run_keys(['d', '\t', 'q'], [('RUNNING', [link()], [link(2)])])
        output = io.StringIO()
        Console(file=output, width=80, height=18).print(live.update.call_args.args[0])
        self.assertIn('Selected ID: 1', output.getvalue())
        self.assertIn('Running: 1-1/1', output.getvalue())

    def test_unhandled_detail_keys_never_reach_queue_navigation(self):
        snapshots = [('RUNNING', [], [link()])] * 2
        with patch.object(Navigation, 'handle_key', autospec=True, return_value=True) as handler:
            self.run_keys(['d', 'future-key', 'q'], snapshots)
        handler.assert_not_called()

    def test_controller_action_marks_capture_stale_until_explicit_refresh(self):
        client, live = self.run_keys(['d', 's'], [('RUNNING', [], [link()]), ('STOPPED', [], [link()])])
        output = io.StringIO()
        Console(file=output, width=80, height=18).print(live.update.call_args.args[0])
        self.assertIn('Controller action requested', output.getvalue())
        self.assertIn('Refresh needed', output.getvalue())
        client.device.downloads.query_links.assert_called_once()
        details = Details()
        details.fetch(self.device(), 1)
        details.controller_requested = True
        details.fetch(self.device(), 1)
        self.assertFalse(details.controller_requested)

    def test_unexpected_service_programming_error_is_not_hidden(self):
        details = Details()
        with patch.object(services, 'explain_download', side_effect=RuntimeError('programming failure')):
            with self.assertRaisesRegex(RuntimeError, 'programming failure'):
                details.fetch(self.device(), 1)


if __name__ == '__main__':
    unittest.main()
