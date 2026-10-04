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

    def test_operation_error_survives_multiple_polls_then_expires(self):
        client = MagicMock()
        client.settings = config.Settings(refresh_rate=0.5)
        client.fetch_stats.return_value = ('STOPPED', [], [])
        client.toggle_state.side_effect = ServiceError('start denied')
        now = [0.0]
        events = iter(['s', 1.0, 3.0, 6.0, KeyboardInterrupt])

        def key():
            event = next(events)
            if event is KeyboardInterrupt:
                raise KeyboardInterrupt
            if event == 's':
                return event
            now[0] = event
            return None

        with patch.object(tui, 'Console'), patch.object(tui, 'Live'), \
             patch.object(tui, 'generate_layout') as render, patch.object(tui, 'KeyboardInput') as keyboard, \
             patch.object(tui.time, 'monotonic', side_effect=lambda: now[0]), patch.object(tui.time, 'sleep'):
            keyboard.return_value.__enter__.return_value.get_key.side_effect = key
            tui.run(client)
        statuses = [c.kwargs.get('override_status') for c in render.call_args_list]
        self.assertGreaterEqual(statuses.count('ERROR: start denied'), 3)
        self.assertIsNone(statuses[-1])
        self.assertEqual(client.fetch_stats.call_count, 5)

    def test_custom_refresh_rate_controls_polling(self):
        client = MagicMock()
        client.settings = config.Settings(refresh_rate=0.25)
        client.fetch_stats.return_value = ('STOPPED', [], [])
        now = [0.0]

        def key():
            if client.fetch_stats.call_count > 1:
                raise KeyboardInterrupt
            return None

        def sleep(seconds):
            now[0] += seconds

        with patch.object(tui, 'Console'), patch.object(tui, 'Live'), \
             patch.object(tui, 'generate_layout'), patch.object(tui, 'KeyboardInput') as keyboard, \
             patch.object(tui.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(tui.time, 'sleep', side_effect=sleep) as pauses:
            keyboard.return_value.__enter__.return_value.get_key.side_effect = key
            tui.run(client)
        self.assertEqual(pauses.call_count, 3)
        self.assertEqual(client.fetch_stats.call_count, 2)

    def test_error_markup_is_literal_and_long_messages_do_not_expand_rows(self):
        from rich.console import Console
        for message in ('ERROR: [errno 111] [red]refused[/red]', 'ERROR: line\n' + 'x' * 1000):
            with self.subTest(message=message):
                output = io.StringIO()
                console = Console(file=output, width=120, height=20, force_terminal=False)
                console.print(tui.generate_layout('ERROR', [], [], override_status=message))
                self.assertEqual(len(output.getvalue().splitlines()), 20)
                if '[errno' in message:
                    self.assertIn('[errno 111]', output.getvalue())
                else:
                    self.assertIn('…', output.getvalue())


    def test_tiny_refresh_rate_has_minimum_polling_interval(self):
        client = MagicMock()
        client.settings = config.Settings(refresh_rate=1e-9)
        client.fetch_stats.return_value = ('STOPPED', [], [])
        now = [0.0]

        def key():
            if client.fetch_stats.call_count > 1:
                raise KeyboardInterrupt
            return None

        def sleep(seconds):
            now[0] += seconds

        with patch.object(tui, 'Console'), patch.object(tui, 'Live'), \
             patch.object(tui, 'generate_layout'), patch.object(tui, 'KeyboardInput') as keyboard, \
             patch.object(tui.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(tui.time, 'sleep', side_effect=sleep) as pauses:
            keyboard.return_value.__enter__.return_value.get_key.side_effect = key
            tui.run(client)
        self.assertEqual(pauses.call_count, 1)
        self.assertEqual(client.fetch_stats.call_count, 2)


class DebugAndStartupTests(unittest.TestCase):
    def test_debug_traceback_goes_to_stderr_and_logger_state_is_restored(self):
        import logging
        logger = logging.getLogger('jdsh')
        previous = (logger.level, logger.propagate, list(logger.handlers))
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict('os.environ', {'JDSH_DEBUG': '1'}), \
             patch.object(cli, '_main', side_effect=TypeError('programming failure')), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                cli.main(['status'])
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('Traceback', stderr.getvalue())
        self.assertIn('TypeError: programming failure', stderr.getvalue())
        self.assertEqual((logger.level, logger.propagate, list(logger.handlers)), previous)

    def test_default_errors_remain_without_tracebacks(self):
        with patch.dict('os.environ', {'JDSH_DEBUG': '0'}), \
             patch.object(cli, '_main', side_effect=TypeError('failure')), \
             patch('sys.stderr', new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit):
                cli.main(['status'])
        self.assertEqual(stderr.getvalue(), 'Error: failure\n')

    def test_no_argument_startup_loads_connects_then_runs_tui(self):
        settings = config.Settings('example.org', 1234, 0.25)
        events = MagicMock()
        with patch.object(cli.config, 'load_settings', events.load), \
             patch.object(cli, 'JDClient', events.client), patch.object(cli.tui, 'run', events.tui):
            events.load.return_value = settings
            cli.main([])
        from unittest.mock import call
        self.assertEqual(events.mock_calls, [
            call.load(), call.client(settings), call.client().connect(), call.tui(events.client.return_value, console=None),
        ])

    def test_replace_cli_failure_never_prints_success(self):
        client = MagicMock()
        client.connect.return_value.linkgrabber.add_links.side_effect = RuntimeError('add denied')
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(cli.config, 'load_settings', return_value=config.Settings()), \
             patch.object(cli, 'JDClient', return_value=client), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as caught:
                cli.main(['replace', '123', 'https://example.org'])
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('was removed, but adding', stderr.getvalue())

    def test_clipboard_error_uses_common_application_base(self):
        from jdsh.clipboard import ClipboardError
        from jdsh.errors import JDShError
        self.assertTrue(issubclass(ClipboardError, JDShError))

    def test_dispatch_reports_missing_handler_explicitly(self):
        from types import SimpleNamespace
        with patch.object(cli, '_parse_args', return_value=SimpleNamespace(command='future')), \
             patch.object(cli.config, 'load_settings', return_value=config.Settings()), \
             patch.object(cli, 'JDClient'), patch('sys.stderr', new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit):
                cli.main(['future'])
        self.assertIn('Unsupported command: future', stderr.getvalue())

    def test_debug_includes_polling_failure(self):
        client = MagicMock()
        client.fetch_stats.side_effect = StatsError('offline')
        with patch.dict('os.environ', {'JDSH_DEBUG': '1'}), patch('sys.stderr', new_callable=io.StringIO) as stderr:
            with cli._debug_logging():
                self.assertEqual(tui._poll_stats(client)[0], 'ERROR')
        self.assertIn('Polling failed', stderr.getvalue())
        self.assertIn('StatsError: offline', stderr.getvalue())
