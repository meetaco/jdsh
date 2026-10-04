import contextlib
import io
import json
import unittest
from unittest.mock import MagicMock, patch

from rich.console import Console

from jdsh import cli, config, rendering, tui
from jdsh.diagnostics import diagnose_link


class TransferRenderingTests(unittest.TestCase):
    @staticmethod
    def link(**values):
        return {'uuid': 123, 'name': 'file.zip', 'running': True, 'enabled': True,
                'bytesLoaded': 512, 'bytesTotal': 1024, 'speed': 256, 'eta': 2, **values}

    @staticmethod
    def console(stream):
        return Console(file=stream, force_terminal=False, width=240, height=26)

    def test_cli_and_tui_share_size_speed_and_percentage_for_known_transfer(self):
        link = self.link()
        cli_output, tui_output = io.StringIO(), io.StringIO()
        rendering.render_status('RUNNING', [link], console=self.console(cli_output))
        self.console(tui_output).print(tui.generate_layout('RUNNING', [link], []))
        for output in (cli_output.getvalue(), tui_output.getvalue()):
            self.assertIn('512.00 B/1.00 KB', output)
            self.assertIn('256.00 B/s', output)
            self.assertIn('50', output)
        self.assertIn('50.0%', cli_output.getvalue())
        self.assertIn('50%', tui_output.getvalue())

    def test_cli_and_tui_handle_null_and_zero_without_fabricating_total(self):
        for total in (None, 0, -1):
            with self.subTest(total=total):
                link = self.link(bytesLoaded=0, bytesTotal=total, speed=None, eta=None)
                cli_output, tui_output = io.StringIO(), io.StringIO()
                rendering.render_status('RUNNING', [link], console=self.console(cli_output))
                self.console(tui_output).print(tui.generate_layout('RUNNING', [link], []))
                expected = '0 B/0 B' if total == 0 else '0 B/null'
                for output in (cli_output.getvalue(), tui_output.getvalue()):
                    self.assertIn(expected, output)
                    self.assertIn('null/s', output)
                    self.assertNotIn('1.00 B', output)
                    row = next(line for line in output.splitlines() if 'file.zip' in line)
                    self.assertNotIn('%', row)

    def test_empty_messages_use_injected_console_without_stdout(self):
        for render, message in [(rendering.render_list, 'Download queue is empty.'),
                                (rendering.render_grabber, 'LinkGrabber is empty.')]:
            output, stdout = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout):
                render([], console=self.console(output))
            self.assertIn(message, output.getvalue())
            self.assertEqual(stdout.getvalue(), '')

    def test_all_rich_renderers_accept_console_without_constructing_another(self):
        link = self.link()
        diagnosis = diagnose_link(link)
        cases = [
            (rendering.print_help, ()),
            (rendering.render_message, ('literal [red] feedback',)),
            (rendering.render_show, ({'link': link, 'package': None, 'downloadUrls': {}, 'diagnosis': diagnosis}, 123)),
            (rendering.render_why, ({'uuid': 123, 'diagnosis': diagnosis},)),
            (rendering.render_check, ({'uuid': 123},)),
            (rendering.render_check_all, ({'started': True, 'linkCount': 2},)),
            (rendering.render_list, ([link],)),
            (rendering.render_grabber, ([link],)),
            (rendering.render_status, ('RUNNING', [link])),
        ]
        for render, args in cases:
            with self.subTest(render=render.__name__):
                output, stdout = io.StringIO(), io.StringIO()
                with patch.object(rendering, 'Console', side_effect=AssertionError('must use supplied console')), \
                     contextlib.redirect_stdout(stdout):
                    render(*args, console=self.console(output))
                self.assertTrue(output.getvalue())
                self.assertEqual(stdout.getvalue(), '')

    def test_main_routes_status_to_console_and_json_to_stdout(self):
        client = MagicMock()
        client.connect.return_value.downloadcontroller.get_current_state.return_value = 'RUNNING'
        client.connect.return_value.downloads.query_links.return_value = [self.link()]
        client.connect.return_value.action.return_value = {}
        for argv in (['status'], ['start'], ['show', '123', '--json']):
            with self.subTest(argv=argv):
                output, stdout = io.StringIO(), io.StringIO()
                with patch.object(cli.config, 'load_settings', return_value=config.Settings()), \
                     patch.object(cli, 'JDClient', return_value=client), contextlib.redirect_stdout(stdout):
                    cli.main(argv, console=self.console(output))
                if '--json' in argv:
                    self.assertEqual(json.loads(stdout.getvalue())['link']['bytesTotal'], 1024)
                    self.assertEqual(output.getvalue(), '')
                else:
                    expected = 'Command executed: start' if argv == ['start'] else 'file.zip'
                    self.assertIn(expected, output.getvalue())
                    self.assertEqual(stdout.getvalue(), '')

    def test_tui_live_uses_the_supplied_console(self):
        client = MagicMock()
        client.settings = config.Settings()
        client.fetch_stats.return_value = ('STOPPED', [], [])
        console = self.console(io.StringIO())
        with patch.object(tui, 'Console', side_effect=AssertionError('must use supplied console')), \
             patch.object(console, 'clear'), patch.object(tui, 'Live') as live, \
             patch.object(tui, 'KeyboardInput') as keyboard, patch.object(tui.time, 'monotonic', return_value=0):
            keyboard.return_value.__enter__.return_value.get_key.side_effect = KeyboardInterrupt
            tui.run(client, console=console)
        live.assert_called_once_with(console=console, refresh_per_second=4, screen=True)

    def test_status_requests_finished_and_excludes_finished_running_link(self):
        device = MagicMock()
        device.downloadcontroller.get_current_state.return_value = 'RUNNING'
        links = [self.link(finished=False), self.link(name='finished.zip', finished=True, speed=999)]

        def query(queries):
            # Simulate the API returning only the requested fields.
            return [{key: value for key, value in link.items() if queries[0].get(key)} for link in links]

        device.downloads.query_links.side_effect = query
        output = io.StringIO()
        cli.cmd_status(device, None, console=self.console(output))
        self.assertIs(device.downloads.query_links.call_args.args[0][0]['finished'], True)
        self.assertRegex(output.getvalue(), r'Active:\s+1')
        self.assertIn('256.00 B/s', output.getvalue())
        self.assertNotIn('finished.zip', output.getvalue())

    def test_mixed_unknown_speed_is_not_displayed_as_partial_total(self):
        links = [self.link(name='known.zip'), self.link(name='unknown.zip', speed=None)]
        cli_output, tui_output = io.StringIO(), io.StringIO()
        rendering.render_status('RUNNING', links, console=self.console(cli_output))
        self.console(tui_output).print(tui.generate_layout('RUNNING', links, []))
        for output in (cli_output.getvalue(), tui_output.getvalue()):
            self.assertRegex(output, r'Speed:\s+null/s')
            self.assertIn('256.00 B/s', output)

    def test_near_complete_percentage_is_not_displayed_as_one_hundred(self):
        link = self.link(bytesLoaded=9996, bytesTotal=10000)
        cli_output, tui_output = io.StringIO(), io.StringIO()
        rendering.render_status('RUNNING', [link], console=self.console(cli_output))
        self.console(tui_output).print(tui.generate_layout('RUNNING', [link], []))
        self.assertIn('99.9%', cli_output.getvalue())
        self.assertIn('99%', tui_output.getvalue())
        self.assertNotIn('100%', tui_output.getvalue())

    def test_command_messages_remain_literal_without_numeric_highlighting(self):
        output = io.StringIO()
        console = Console(file=output, force_terminal=True, width=240)
        rendering.render_check_all({'started': True, 'linkCount': 151}, console=console)
        rendering.render_check_all({'started': False}, console=console)
        rendering.render_list([], console=console)
        rendering.render_grabber([], console=console)
        self.assertIn('151 links', output.getvalue())
        self.assertNotIn('\x1b', output.getvalue())

    def test_names_with_markup_are_rendered_literally_in_cli_and_tui(self):
        link = self.link(name='[red]file[/red].zip')
        outputs = []
        for render in (rendering.render_status, rendering.render_list, rendering.render_grabber):
            stream = io.StringIO()
            if render is rendering.render_status:
                render('RUNNING', [link], console=self.console(stream))
            else:
                render([link], console=self.console(stream))
            outputs.append(stream.getvalue())
        stream = io.StringIO()
        self.console(stream).print(tui.generate_layout('RUNNING', [link], []))
        outputs.append(stream.getvalue())
        for output in outputs:
            self.assertIn(link['name'], output)

    def test_version_rendering_failure_is_not_treated_as_unknown_core(self):
        device = MagicMock()
        device.action.return_value = 42
        with patch.object(rendering, 'render_message', side_effect=[None, RuntimeError('render denied')]) as render, \
             patch('sys.stderr', new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as caught:
                cli._execute(cli.cmd_version, device, None)
        self.assertEqual(caught.exception.code, 1)
        self.assertIn('render denied', stderr.getvalue())
        self.assertEqual(render.call_count, 2)
        self.assertEqual(render.call_args.args[0], 'JD Core: 42')
