"""Validate all editable values before issuing a single JDownloader request."""

import io
import unittest
from unittest.mock import MagicMock, patch

from rich.console import Console
from myjdapi.myjdapi import Downloads

from jdsh import arguments, cli, services


class RecordingDevice:
    def __init__(self, result=None):
        self.requests = []
        self.result = result
        self.downloads = Downloads(self)
    def action(self, endpoint, params):
        self.requests.append((endpoint, params))
        return self.result


class DownloadSettingsTests(unittest.TestCase):
    def test_valid_cli_dispatch_and_exact_payloads(self):
        cases = (
            (['reset', '1', '--yes', '--package', '3', '1'], '/downloadsV2/resetLinks', [[1], [3]]),
            (['reset', '--package', '3', '--yes'], '/downloadsV2/resetLinks', [[], [3]]),
            (['priority', 'high', '1', '--package', '3', '2'], '/downloadsV2/setPriority', ['HIGH', [1, 2], [3]]),
            (['priority', '--package', '3', 'low'], '/downloadsV2/setPriority', ['LOW', [], [3]]),
            (['rename', 'new name.zip', '--link', '1'], '/downloadsV2/renameLink', [1, 'new name.zip']),
            (['rename', '--package', '3', 'new package'], '/downloadsV2/renamePackage', [3, 'new package']),
            (['rename', '--link', '1', '--', '-name.zip'], '/downloadsV2/renameLink', [1, '-name.zip']),
            (['directory', '/downloads/space dir', '--package', '3', '--package', '3'], '/downloadsV2/setDownloadDirectory', ['/downloads/space dir', [3]]),
            (['directory', '--package', '3', r'C:\Downloads\new'], '/downloadsV2/setDownloadDirectory', [r'C:\Downloads\new', [3]]),
        )
        for argv, endpoint, payload in cases:
            with self.subTest(argv=argv):
                client = MagicMock()
                device = RecordingDevice()
                client.connect.return_value = device
                output = io.StringIO()
                with patch.object(cli.config, 'load_settings'), patch.object(cli, 'JDClient', return_value=client):
                    cli.main(argv, console=Console(file=output, width=160))
                self.assertEqual(device.requests, [(endpoint, payload)])
                self.assertIn('Submitted', output.getvalue())

    def test_invalid_cli_never_loads_settings_or_connects(self):
        cases = (
            ['reset', '1'], ['reset', '--yes'], ['reset', '1_2', '--yes'],
            ['priority', 'bad', '1'], ['priority', 'high'], ['priority', 'high', '--package', '+1'],
            ['rename', 'name'], ['rename', 'name', '--link', '1', '--package', '3'],
            ['rename', 'name', '--link', '1', '--link', '2'],
            ['rename', 'name', '--package', '1', '--package', '2'],
            ['rename', '', '--link', '1'], ['rename', 'a/b', '--link', '1'],
            ['rename', '..', '--link', '1'], ['rename', 'x\x85y', '--package', '1'], ['rename', 'a\\b', '--link', '1'],
            ['directory', '/downloads'], ['directory', '/downloads', '--link', '1'],
            ['directory', 'relative', '--package', '1'], ['directory', '~/downloads', '--package', '1'],
            ['directory', '/a\x85', '--package', '1'], ['directory', 'C:relative', '--package', '1'], ['directory', '/a\n', '--package', '1'],
            ['reset', '1', '--y'], ['priority', 'high', '1', '--pack', '3'],
            ['rename', 'name', '--pack', '1'], ['directory', '/downloads', '--pack', '1'],
        )
        for argv in cases:
            with self.subTest(argv=argv), patch.object(cli.config, 'load_settings') as settings, \
                 patch.object(cli, 'JDClient') as client, patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as caught:
                    cli.main(argv)
                self.assertEqual(caught.exception.code, 2)
                settings.assert_not_called()
                client.assert_not_called()

    def test_direct_service_validation_prevents_requests(self):
        cases = (
            lambda d: services.reset_downloads(d, [1]),
            lambda d: services.reset_downloads(d, [1], confirmed=1),
            lambda d: services.reset_downloads(d, [], confirmed=True),
            lambda d: services.set_download_priority(d, 'bad', [1]),
            lambda d: services.set_download_priority(d, 'high'),
            lambda d: services.rename_download(d, 'name', [1, 2]),
            lambda d: services.rename_download(d, 'name', [1], [3]),
            lambda d: services.rename_download(d, 'a/b', [1]),
            lambda d: services.rename_download(d, ' \n', package_ids=[3]),
            lambda d: services.set_download_directory(d, '/downloads', []),
            lambda d: services.set_download_directory(d, 'relative', [3]),
            lambda d: services.set_download_directory(d, '/downloads', ['1_2']),
        )
        for operation in cases:
            device = RecordingDevice()
            with self.assertRaises(ValueError):
                operation(device)
            self.assertEqual(device.requests, [])

    def test_false_and_exception_have_no_success_and_no_retry(self):
        for argv in (['reset', '1', '--yes'], ['priority', 'high', '1'],
                     ['rename', 'name', '--package', '3'], ['directory', '/downloads', '--package', '3']):
            for error in (False, RuntimeError('denied')):
                device = MagicMock()
                if error is False:
                    device.action.return_value = False
                else:
                    device.action.side_effect = error
                output = io.StringIO()
                with patch('sys.stderr', new_callable=io.StringIO) as stderr:
                    with self.assertRaises(SystemExit) as caught:
                        cli._execute(lambda: cli.cmd_download_setting(device, arguments.parse_args(argv), console=Console(file=output)))
                self.assertEqual(caught.exception.code, 1)
                self.assertEqual(output.getvalue(), '')
                self.assertIn('Error:', stderr.getvalue())
                device.action.assert_called_once()
                device.downloadcontroller.start_downloads.assert_not_called()

    def test_paths_and_names_are_passed_without_local_expansion_or_markup(self):
        device = RecordingDevice()
        services.rename_download(device, '[red]File.zip', [1])
        services.rename_download(device, 'a/b', package_ids=[3])
        services.set_download_directory(device, r'\\server\share\folder', [3])
        self.assertEqual(device.requests, [('/downloadsV2/renameLink', [1, '[red]File.zip']),
                                          ('/downloadsV2/renamePackage', [3, 'a/b']),
                                          ('/downloadsV2/setDownloadDirectory', [r'\\server\share\folder', [3]])])

    def test_reset_raw_request_matches_real_sdk_route(self):
        device = RecordingDevice()
        services.reset_downloads(device, [1], [3], confirmed=True)
        expected = list(device.requests)
        device.requests.clear()
        device.downloads.reset_links([1], [3])
        self.assertEqual(device.requests, expected)
