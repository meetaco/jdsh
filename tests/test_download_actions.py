"""Download actions must submit exactly one request for an explicit selection."""

import io
import unittest
from unittest.mock import MagicMock, call, patch

from rich.console import Console

from jdsh import arguments, cli, services
from jdsh.download_selection import SELECTED_COMMANDS, select_downloads


class SelectionTests(unittest.TestCase):
    def test_deduplicates_in_order_without_merging_id_namespaces(self):
        links, packages = [3, 1, 3], [1, 8, 8]
        result = select_downloads(links, packages)
        self.assertEqual(result.link_ids, (3, 1))
        self.assertEqual(result.package_ids, (1, 8))
        self.assertEqual(links, [3, 1, 3])
        self.assertEqual(packages, [1, 8, 8])

    def test_direct_service_rejects_empty_or_invalid_selection_before_any_call(self):
        for links, packages in (([], []), ([0], []), ([], [-1]), ([True], []),
                                ([1.0], []), ([2**63], []), (['bad'], [])):
            with self.subTest(links=links, packages=packages):
                device = MagicMock()
                with self.assertRaises(ValueError):
                    services.apply_download_action(device, 'enable', links, packages)
                self.assertEqual(device.mock_calls, [])

    def test_unsupported_action_makes_no_call(self):
        device = MagicMock()
        with self.assertRaises(ValueError):
            services.apply_download_action(device, 'bad', [1])
        self.assertEqual(device.mock_calls, [])


class ActionArgumentTests(unittest.TestCase):
    def test_both_id_kinds_and_interspersed_options_for_every_command(self):
        for command in SELECTED_COMMANDS:
            for tail in (['1', '--package', '3', '2'],
                         ['--package', '3', '1', '2'],
                         ['1', '2', '--package=3']):
                with self.subTest(command=command, tail=tail):
                    args = arguments.parse_args([command] + tail)
                    self.assertEqual(args.uuids, [1, 2])
                    self.assertEqual(args.package, [3])
            args = arguments.parse_args([command, '--package', '3', '--package', '4'])
            self.assertEqual(args.uuids, [])
            self.assertEqual(args.package, [3, 4])

    def test_invalid_cli_selection_exits_before_config_or_connection(self):
        for command in SELECTED_COMMANDS:
            for tail in ([], ['0'], ['-1'], ['bad'], [str(2**63)], ['--package'],
                         ['--package', '0'], ['1', '--unknown'], ['--', '--package']):
                with self.subTest(command=command, tail=tail), \
                     patch.object(cli.config, 'load_settings') as settings, \
                     patch.object(cli, 'JDClient') as client, \
                     patch('sys.stderr', new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as caught:
                        cli.main([command] + tail)
                    self.assertEqual(caught.exception.code, 2)
                    settings.assert_not_called()
                    client.assert_not_called()

    def test_normalization_preserves_caller_input_and_id_bound(self):
        argv = ['enable', '1', '--package', str(2**63 - 1), '2']
        original = list(argv)
        result = arguments.parse_args(argv)
        self.assertEqual(argv, original)
        self.assertEqual(result.package, [2**63 - 1])


class ActionServiceTests(unittest.TestCase):
    def test_endpoint_order_and_single_submission_for_mixed_selection(self):
        cases = (
            ('enable', call.downloads.set_enabled(True, [3, 1], [8])),
            ('disable', call.downloads.set_enabled(False, [3, 1], [8])),
            ('resume', call.action('/downloadsV2/resumeLinks', [[3, 1], [8]])),
            ('force', call.downloads.force_download([3, 1], [8])),
            ('remove', call.downloads.remove_links([3, 1], [8])),
        )
        for action, expected in cases:
            with self.subTest(action=action):
                device = MagicMock()
                result = services.apply_download_action(device, action, [3, 1, 3], [8, 8])
                self.assertEqual(device.mock_calls, [expected])
                self.assertEqual(result.link_ids, (3, 1))
                self.assertEqual(result.package_ids, (8,))

    def test_package_only_requests_never_expand_to_all(self):
        device = MagicMock()
        services.apply_download_action(device, 'resume', [], [8])
        device.action.assert_called_once_with('/downloadsV2/resumeLinks', [[], [8]])

    def test_false_response_and_exceptions_do_not_print_success_or_retry(self):
        for command, section, method in (
            ('enable', 'downloads', 'set_enabled'), ('disable', 'downloads', 'set_enabled'),
            ('resume', None, 'action'), ('force', 'downloads', 'force_download'),
            ('remove', 'downloads', 'remove_links'), ('rm', 'downloads', 'remove_links'),
        ):
            for failure in (False, RuntimeError('operation denied')):
                with self.subTest(command=command, failure=failure):
                    device = MagicMock()
                    target = getattr(device, section) if section else device
                    operation = getattr(target, method)
                    if failure is False:
                        operation.return_value = False
                    else:
                        operation.side_effect = failure
                    output = io.StringIO()
                    handler = cli.cmd_remove if command in ('remove', 'rm') else cli.cmd_download_action
                    with patch('sys.stderr', new_callable=io.StringIO) as stderr:
                        with self.assertRaises(SystemExit) as caught:
                            cli._execute(lambda: handler(device, arguments.parse_args([command, '--package', '8']),
                                                console=Console(file=output)))
                    self.assertEqual(caught.exception.code, 1)
                    self.assertEqual(output.getvalue(), '')
                    self.assertIn('Error:', stderr.getvalue())
                    operation.assert_called_once()
                    device.downloadcontroller.start_downloads.assert_not_called()

    def test_cli_routing_reports_unique_id_counts_as_requests(self):
        for command in SELECTED_COMMANDS:
            with self.subTest(command=command):
                client = MagicMock()
                output = io.StringIO()
                with patch.object(cli.config, 'load_settings'), \
                     patch.object(cli, 'JDClient', return_value=client):
                    cli.main([command, '3', '3', '--package', '8'], console=Console(file=output, width=120))
                action = 'remove' if command == 'rm' else command
                self.assertIn(f'Submitted {action} request for 1 link ID and 1 package ID.', output.getvalue())
                client.connect.return_value.downloadcontroller.start_downloads.assert_not_called()


class ReviewRegressionTests(unittest.TestCase):
    INVALID_TEXT_IDS = ('1_2', '+5', ' 5 ', '１２３', '١٢٣', '', '\t5')

    def test_nondecimal_text_cannot_select_another_id(self):
        for value in self.INVALID_TEXT_IDS:
            for links, packages in (([value], []), ([], [value])):
                device = MagicMock()
                with self.subTest(value=value, links=links), self.assertRaises(ValueError):
                    services.apply_download_action(device, 'remove', links, packages)
                self.assertEqual(device.mock_calls, [])
        self.assertEqual(select_downloads(['00012']).link_ids, (12,))

    def test_cli_rejects_bad_text_before_config_or_client(self):
        for command in SELECTED_COMMANDS + ('replace',):
            for value in self.INVALID_TEXT_IDS:
                tails = [[value, 'https://example.org']] if command == 'replace' else [[value], ['--package', value]]
                for tail in tails:
                    with self.subTest(command=command, tail=tail), \
                         patch.object(cli.config, 'load_settings') as settings, \
                         patch.object(cli, 'JDClient') as client, patch('sys.stderr', new_callable=io.StringIO):
                        with self.assertRaises(SystemExit) as caught:
                            cli.main([command] + tail)
                        self.assertEqual(caught.exception.code, 2)
                        settings.assert_not_called()
                        client.assert_not_called()

    def test_cli_errors_preserve_validator_message_and_selection_usage(self):
        for tail in (['0'], [str(2**63)], ['--package', '0'], ['--package', '-1'], ['1', '--package', '-1', '2']):
            with self.subTest(tail=tail), patch('sys.stderr', new_callable=io.StringIO) as stderr:
                with self.assertRaises(SystemExit):
                    arguments.parse_args(['enable'] + tail)
                text = stderr.getvalue()
                self.assertIn('usage: jd enable', text)
                self.assertIn('download IDs must be', text)
                self.assertNotIn('invalid _download_id value', text)
        with patch('sys.stderr', new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit):
                arguments.parse_args(['enable'])
            self.assertIn('usage: jd enable', stderr.getvalue())

    def test_abbreviations_rejected_in_every_option_position(self):
        for tail in (['--pack', '3', '1', '2'], ['1', '--pack', '3', '2'], ['1', '2', '--pack=3']):
            with patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit) as caught:
                arguments.parse_args(['enable'] + tail)
            self.assertEqual(caught.exception.code, 2)

    def test_missing_package_value_and_help_remain_options(self):
        for tail in (['--package'], ['1', '--package', '--help']):
            with patch('sys.stderr', new_callable=io.StringIO) as stderr:
                with self.assertRaises(SystemExit) as caught:
                    arguments.parse_args(['enable'] + tail)
                self.assertEqual(caught.exception.code, 2)
                self.assertIn('expected one argument', stderr.getvalue())
        with patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as caught:
                arguments.parse_args(['enable', '1', '-h'])
            self.assertEqual(caught.exception.code, 0)

    def test_actual_sdk_with_recording_transport_uses_correct_endpoints(self):
        from myjdapi.myjdapi import Downloads
        from types import SimpleNamespace
        class Transport:
            def __init__(self):
                self.requests = []
                self.downloads = Downloads(self)
            def action(self, endpoint, params):
                self.requests.append((endpoint, params))
                return True if endpoint.endswith('/forceDownload') else None
        for action, endpoint, params in (
            ('enable', '/downloadsV2/setEnabled', [True, [1], [3]]),
            ('disable', '/downloadsV2/setEnabled', [False, [1], [3]]),
            ('resume', '/downloadsV2/resumeLinks', [[1], [3]]),
            ('force', '/downloadsV2/forceDownload', [[1], [3]]),
            ('remove', '/downloadsV2/removeLinks', [[1], [3]]),
        ):
            device = Transport()
            selection = services.apply_download_action(device, action, [1], [3])
            self.assertEqual(device.requests, [(endpoint, params)])
            self.assertEqual(selection.link_ids, (1,))
        # Older embedded callers omit package; both CLI handlers support them.
        device = MagicMock()
        cli.cmd_download_action(device, SimpleNamespace(command='enable', uuids=[1]),
                                console=Console(file=io.StringIO()))
        device.downloads.set_enabled.assert_called_once_with(True, [1], [])

    def test_replacement_invalid_id_has_no_partial_mutation(self):
        device = MagicMock()
        with patch('sys.stderr', new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as caught:
                cli._execute(services.replace_download, device, '1_2', 'https://example.org')
        self.assertEqual(caught.exception.code, 1)
        self.assertIn('ASCII digits', stderr.getvalue())
        self.assertEqual(device.mock_calls, [])

    def test_replacement_false_add_keeps_original_false_remove_reports_partial(self):
        device = MagicMock()
        device.linkgrabber.add_links.return_value = False
        with self.assertRaisesRegex(services.ReplacementError, 'original was not removed'):
            services.replace_download(device, 1, 'https://example.org')
        device.downloads.remove_links.assert_not_called()
        device.linkgrabber.add_links.assert_called_once()
        device = MagicMock()
        device.downloads.remove_links.return_value = False
        with self.assertRaisesRegex(services.ReplacementError, 'Replacement was added'):
            services.replace_download(device, 1, 'https://example.org')
        device.linkgrabber.add_links.assert_called_once()
        device.downloads.remove_links.assert_called_once_with([1], [])
