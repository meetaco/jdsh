import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch

from jdsh import cli, config, services, tui
from jdsh.client import JDClient
from jdsh.errors import ConfigError, JDConnectionError, ServiceError, StatsError


class ClientErrorTests(unittest.TestCase):
    def test_connection_uses_injected_settings(self):
        api = MagicMock()
        client = JDClient(config.Settings('jd.local', 1234), api=api)
        self.assertIs(client.connect(), api.get_device.return_value)
        api.direct_connect.assert_called_once_with('jd.local', 1234)

    def test_connection_failure_raises_without_output_or_exit(self):
        for failure in (False, RuntimeError('network down')):
            with self.subTest(failure=failure):
                api = MagicMock()
                if failure is False:
                    api.direct_connect.return_value = False
                else:
                    api.direct_connect.side_effect = failure
                client = JDClient(api=api)
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(JDConnectionError):
                        client.connect()
                self.assertIsNone(client.device)
                api.get_device.assert_not_called()
                self.assertEqual(stdout.getvalue() + stderr.getvalue(), '')

    def test_stats_failure_keeps_cause(self):
        client = JDClient(api=MagicMock())
        client.device = MagicMock()
        cause = RuntimeError('offline')
        client.device.downloads.query_links.side_effect = cause
        with self.assertRaisesRegex(StatsError, 'offline') as caught:
            client.fetch_stats()
        self.assertIs(caught.exception.__cause__, cause)

    def test_toggle_failure_raises_service_error(self):
        for state, method in [('RUNNING', 'stop_downloads'), ('STOPPED', 'start_downloads')]:
            with self.subTest(state=state):
                client = JDClient(api=MagicMock())
                client.device = MagicMock()
                getattr(client.device.downloadcontroller, method).side_effect = RuntimeError('denied')
                with self.assertRaisesRegex(ServiceError, 'denied'):
                    client.toggle_state(state)

    def test_service_errors_have_common_base(self):
        for error in (services.ShowError, services.CheckError, services.WhyError, services.ReplacementError):
            self.assertTrue(issubclass(error, ServiceError))


class CLIErrorTests(unittest.TestCase):
    def run_failure(self, argv, client, expected):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(cli.config, 'load_settings', return_value=config.Settings()), \
             patch.object(cli, 'JDClient', return_value=client), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as caught:
                cli.main(argv)
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn(expected, stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())

    def test_api_failures_use_stderr_exit_one_without_success_output(self):
        cases = [('status', 'downloadcontroller', 'get_current_state'),
                 ('list', 'downloads', 'query_links'), ('grabber', 'linkgrabber', 'query_links'),
                 ('start', 'downloadcontroller', 'start_downloads'),
                 ('clear', 'downloads', 'cleanup'), ('confirm', 'linkgrabber', 'move_to_downloadlist')]
        for command, namespace, method in cases:
            with self.subTest(command=command):
                client = MagicMock()
                client.connect.return_value.linkgrabber.query_packages.return_value = [{'uuid': 123}]
                getattr(getattr(client.connect.return_value, namespace), method).side_effect = RuntimeError('API unavailable')
                self.run_failure([command], client, 'API unavailable')

    def test_json_failure_does_not_write_stdout(self):
        client = MagicMock()
        client.connect.return_value.downloads.query_links.side_effect = RuntimeError('API unavailable')
        self.run_failure(['show', '123', '--json'], client, 'Failed to query download link')

    def test_connection_failure_is_reported_at_entry(self):
        client = MagicMock()
        client.connect.side_effect = JDConnectionError('Connection Error: refused')
        self.run_failure(['list'], client, 'Connection Error: refused')

    def test_invalid_settings_prevent_connection(self):
        with patch.object(cli.config, 'load_settings', side_effect=ConfigError('PORT invalid')), \
             patch.object(cli, 'JDClient') as client, patch('sys.stderr', new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as caught:
                cli.main(['list'])
        self.assertEqual(caught.exception.code, 1)
        self.assertIn('PORT invalid', stderr.getvalue())
        client.assert_not_called()

    def test_help_does_not_load_settings_or_create_client(self):
        for argv in (['help'], ['--help']):
            with self.subTest(argv=argv), patch.object(cli.config, 'load_settings') as load, \
                 patch.object(cli, 'JDClient') as client, patch.object(cli, 'print_help') as help:
                cli.main(argv)
                load.assert_not_called()
                client.assert_not_called()
                help.assert_called_once()

    def test_parser_exit_two_is_preserved(self):
        with patch('sys.stderr', new_callable=io.StringIO), patch.object(cli, 'JDClient') as client:
            with self.assertRaises(SystemExit) as caught:
                cli.main(['check'])
        self.assertEqual(caught.exception.code, 2)
        client.assert_not_called()

    def test_ctrl_c_is_not_converted_to_operation_error(self):
        with self.assertRaises(KeyboardInterrupt):
            cli._execute(MagicMock(side_effect=KeyboardInterrupt))


class ReplacementTests(unittest.TestCase):
    def test_removal_failure_prevents_addition(self):
        device = MagicMock()
        device.downloads.remove_links.side_effect = RuntimeError('remove denied')
        with self.assertRaisesRegex(services.ReplacementError, 'Failed to remove original'):
            services.replace_download(device, '123', 'https://example.org')
        device.linkgrabber.add_links.assert_not_called()

    def test_addition_failure_reports_removed_original(self):
        device = MagicMock()
        device.linkgrabber.add_links.side_effect = RuntimeError('add denied')
        with self.assertRaisesRegex(services.ReplacementError, 'was removed, but adding'):
            services.replace_download(device, '123', 'https://example.org')
        device.downloads.remove_links.assert_called_once_with(['123'], [])

    def test_success_keeps_existing_api_order_and_parameters(self):
        device = MagicMock()
        services.replace_download(device, '123', 'https://example.org')
        from unittest.mock import call
        self.assertEqual(device.mock_calls, [
            call.downloads.remove_links(['123'], []),
            call.linkgrabber.add_links([{'links': 'https://example.org', 'autostart': True, 'packageName': 'Rep_123'}]),
        ])


class TUIErrorTests(unittest.TestCase):
    def test_poll_failure_provides_visible_reason_and_can_recover(self):
        client = MagicMock()
        client.fetch_stats.side_effect = [StatsError('offline'), ('STOPPED', [], [])]
        self.assertEqual(tui._poll_stats(client), ('ERROR', [], [], 'ERROR: offline'))
        self.assertEqual(tui._poll_stats(client), ('STOPPED', [], [], None))

    def test_toggle_failure_is_rendered_instead_of_discarded(self):
        client = MagicMock()
        client.settings = config.Settings()
        client.fetch_stats.return_value = ('STOPPED', [], [])
        client.toggle_state.side_effect = ServiceError('start denied')
        with patch.object(tui, 'Console'), patch.object(tui, 'Live'), \
             patch.object(tui, 'generate_layout') as render, patch.object(tui, 'KeyboardInput') as keyboard, \
             patch.object(tui.time, 'monotonic', return_value=0.0):
            keyboard.return_value.__enter__.return_value.get_key.side_effect = ['s', KeyboardInterrupt]
            tui.run(client)
        self.assertTrue(any(c.kwargs.get('override_status') == 'ERROR: start denied' for c in render.call_args_list))
        client.toggle_state.assert_called_once_with('STOPPED')

    def test_failed_poll_does_not_toggle_from_unknown_state(self):
        client = MagicMock()
        client.settings = config.Settings()
        client.fetch_stats.side_effect = StatsError('offline')
        with patch.object(tui, 'Console'), patch.object(tui, 'Live'), \
             patch.object(tui, 'generate_layout'), patch.object(tui, 'KeyboardInput') as keyboard, \
             patch.object(tui.time, 'monotonic', return_value=0.0), patch.object(tui.time, 'sleep'):
            keyboard.return_value.__enter__.return_value.get_key.side_effect = ['s', KeyboardInterrupt]
            tui.run(client)
        client.toggle_state.assert_not_called()
