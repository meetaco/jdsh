"""Help must work offline and obey command/argument boundaries."""

import io
import unittest
from unittest.mock import MagicMock, patch

from rich.console import Console

from jdsh import cli


class CommandHelpTests(unittest.TestCase):
    def test_every_command_has_offline_specific_help(self):
        commands = ('status', 'list', 'ls', 'show', 'why', 'check', 'grabber',
                    'confirm', 'start', 'stop', 'clear', 'version', 'help',
                    'add', 'remove', 'rm', 'replace', 'enable', 'disable', 'resume', 'force', 'reset', 'priority', 'rename', 'directory')
        for command in commands:
            for flag in ('-h', '--help'):
                with self.subTest(command=command, flag=flag), \
                     patch.object(cli.config, 'load_settings') as settings, \
                     patch.object(cli, 'JDClient') as client, \
                     patch('sys.stdout', new_callable=io.StringIO) as output:
                    with self.assertRaises(SystemExit) as caught:
                        cli.main([command, flag])
                    self.assertEqual(caught.exception.code, 0)
                    canonical = {'ls': 'list', 'rm': 'remove'}.get(command, command)
                    self.assertIn('usage: jd ' + canonical, output.getvalue())
                    settings.assert_not_called()
                    client.assert_not_called()

    def test_add_help_explains_sources_and_next_steps(self):
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            with self.assertRaises(SystemExit):
                cli.main(['add', '--help'])
        text = output.getvalue()
        for expected in ('--clipboard', '--file', 'URL', 'jd confirm', 'jd start'):
            self.assertIn(expected, text)

    def test_unknown_command_with_help_still_fails(self):
        with patch('sys.stderr', new_callable=io.StringIO), \
             patch.object(cli, 'JDClient') as client:
            with self.assertRaises(SystemExit) as caught:
                cli.main(['unknown', '--help'])
            self.assertEqual(caught.exception.code, 2)
            client.assert_not_called()

    def test_literal_help_after_terminator_is_submitted(self):
        client = MagicMock()
        with patch.object(cli.config, 'load_settings'), \
             patch.object(cli, 'JDClient', return_value=client):
            cli.main(['add', '--', '--help'], console=Console(file=io.StringIO()))
        client.connect.return_value.linkgrabber.add_links.assert_called_once_with([{
            'links': '--help', 'autostart': False, 'priority': 'DEFAULT',
        }])

    def test_confirm_reports_move_and_does_not_start_controller(self):
        device = MagicMock()
        device.linkgrabber.query_packages.return_value = [{'uuid': 123}]
        output = io.StringIO()
        cli.cmd_confirm(device, None, console=Console(file=output, width=120))
        self.assertIn('Moved 1 packages to the download queue.', output.getvalue())
        self.assertIn("jd start", output.getvalue())
        device.downloadcontroller.start_downloads.assert_not_called()
