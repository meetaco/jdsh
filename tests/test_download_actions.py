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
                self.assertIn(f'Submitted {action} request for 1 link IDs and 1 package IDs.', output.getvalue())
                client.connect.return_value.downloadcontroller.start_downloads.assert_not_called()
