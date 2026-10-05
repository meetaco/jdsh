"""Navigation boundaries, streamed keys, and actual Rich viewports without a JD."""

import io
import os
import select
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.console import Console

from jdsh import tui
from jdsh.client import TUI_LINK_STATE_QUERY
from jdsh.tui_navigation import KeyDecoder, Navigation
from jdsh.tui_runtime import run_loop


def rows(first, count):
    return [dict(uuid=i, name=f'link-{i}', bytesTotal=100, bytesLoaded=10)
            for i in range(first, first + count)]


class NavigationTests(unittest.TestCase):
    def test_move_page_boundaries_and_independent_pane_positions(self):
        nav = Navigation()
        nav.sync(rows(1, 20), rows(101, 20))
        nav.resize((4, 3))
        nav.handle_key('pagedown')
        self.assertEqual(nav.selected_id, 5)
        self.assertEqual([r['uuid'] for r in nav.visible(0)], [2, 3, 4, 5])
        nav.handle_key('\t')
        nav.handle_key('end')
        self.assertEqual(nav.selected_id, 120)
        self.assertEqual([r['uuid'] for r in nav.visible(1)], [118, 119, 120])
        nav.handle_key('down')
        self.assertEqual(nav.selected_id, 120)
        nav.handle_key('\t')
        self.assertEqual(nav.selected_id, 5)
        nav.handle_key('home')
        nav.handle_key('k')
        self.assertEqual(nav.selected_id, 1)
        self.assertEqual(nav.offsets[0], 0)

    def test_refresh_reordering_insertion_and_pane_migration_keep_selected_id(self):
        nav = Navigation()
        initial = rows(1, 4)
        nav.sync(initial, [])
        nav.handle_key('j')
        self.assertEqual(nav.selected_id, 2)
        nav.sync([initial[3], initial[0], initial[2], initial[1]], [])
        self.assertEqual(nav.selected_id, 2)
        self.assertEqual(nav.indices[0], 3)
        nav.sync(rows(20, 5), [initial[1]])
        self.assertEqual(nav.pane, 1)
        self.assertEqual(nav.selected_id, 2)
        self.assertEqual(initial, rows(1, 4))

    def test_disappearance_empty_data_and_missing_ids_are_safe(self):
        nav = Navigation()
        nav.sync(rows(1, 3), [])
        nav.handle_key('end')
        nav.sync(rows(1, 2), [])
        self.assertEqual(nav.selected_id, 2)
        nav.sync([], rows(100, 1))
        self.assertEqual(nav.selected_id, 100)
        nav.sync([], [])
        for key in ('up', 'down', 'pageup', 'pagedown', 'home', 'end', '\t'):
            nav.handle_key(key)
        self.assertIsNone(nav.selected_id)
        self.assertEqual(nav.visible(0), [])
        nav.sync([{'name': 'legacy'}], [])
        self.assertIsNone(nav.selected_id)
        self.assertFalse(nav.handle_key('s'))

    def test_tab_can_focus_an_empty_pane_until_rows_arrive(self):
        nav = Navigation()
        running = rows(1, 2)
        nav.sync(running, [])
        nav.handle_key('\t')
        nav.sync(running, [])
        self.assertEqual(nav.pane, 1)
        self.assertIsNone(nav.selected_id)
        nav.sync(running, rows(100, 2))
        self.assertEqual(nav.selected_id, 100)
        nav.handle_key('\t')
        self.assertEqual(nav.selected_id, 1)

    def test_resize_keeps_selection_visible_without_requesting_more_data(self):
        nav = Navigation()
        nav.sync(rows(1, 40), [])
        nav.resize((10, 2))
        nav.handle_key('end')
        nav.resize((2, 1))
        self.assertEqual([r['uuid'] for r in nav.visible(0)], [39, 40])
        nav.resize((60, 1))
        self.assertEqual(nav.offsets[0], 0)
        self.assertEqual(nav.selected_id, 40)


class KeyInputTests(unittest.TestCase):
    def test_fragmented_ansi_and_application_keys_do_not_leak_bytes(self):
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed('\x1b'), [])
        self.assertEqual(decoder.feed('['), [])
        self.assertEqual(decoder.feed('Bj\x1bOA\x1b[5~\x1b[6~\x1b[H\x1b[F'),
                         ['down', 'j', 'up', 'pageup', 'pagedown', 'home', 'end'])
        self.assertEqual(decoder.feed('\x1b[99s'), [])
        self.assertEqual(decoder.feed('s'), ['s'])

    def test_posix_bulk_read_and_fragmented_sequences(self):
        keyboard = tui.KeyboardInput()
        with patch.object(tui, 'termios', object()), patch.object(tui.select, 'select', return_value=([0], [], [])), \
             patch.object(tui.os, 'read', side_effect=[b'\x1b', b'[', b'Bj']):
            self.assertIsNone(keyboard.get_key())
            self.assertIsNone(keyboard.get_key())
            self.assertEqual(keyboard.get_key(), 'down')
            self.assertEqual(keyboard.get_key(), 'j')

    @unittest.skipIf(tui.termios is None, 'POSIX terminal test')
    def test_real_pty_arrow_input_and_terminal_restoration_on_exception(self):
        master, slave = os.openpty()
        try:
            with os.fdopen(slave, 'r') as stream:
                original = tui.termios.tcgetattr(stream)
                with patch.object(tui.sys, 'stdin', stream):
                    with self.assertRaisesRegex(RuntimeError, 'stop'):
                        with tui.KeyboardInput() as keyboard:
                            os.write(master, b'\x1b[B')
                            self.assertTrue(select.select([stream], [], [], 1)[0])
                            self.assertEqual(keyboard.get_key(), 'down')
                            raise RuntimeError('stop')
                self.assertEqual(tui.termios.tcgetattr(stream), original)
        finally:
            os.close(master)

    def test_windows_extended_keys_and_control_c(self):
        keyboard = tui.KeyboardInput()
        api = MagicMock()
        api.kbhit.return_value = True
        api.getwch.side_effect = ['\xe0', 'P', '\x00', 'I', 'j', '\x03']
        with patch.object(tui, 'termios', None), patch.object(tui, 'msvcrt', api, create=True):
            self.assertIsNone(keyboard.get_key())
            self.assertEqual(keyboard.get_key(), 'down')
            self.assertIsNone(keyboard.get_key())
            self.assertEqual(keyboard.get_key(), 'pageup')
            self.assertEqual(keyboard.get_key(), 'j')
            with self.assertRaises(KeyboardInterrupt):
                keyboard.get_key()


class NavigationRenderingTests(unittest.TestCase):
    def render(self, nav, running, waiting, height):
        output = io.StringIO()
        console = Console(file=output, width=100, height=height)
        console.print(tui.generate_layout('STOPPED', running, waiting, navigation=nav, height=height))
        return output.getvalue()

    def test_last_waiting_row_is_visible_at_minimum_height_and_after_resize(self):
        running, waiting = rows(1, 30), rows(101, 30)
        nav = Navigation()
        nav.sync(running, waiting)
        nav.handle_key('\t')
        nav.handle_key('end')
        for height in (18, 25, 40, 18):
            text = self.render(nav, running, waiting, height)
            self.assertIn('link-130', text)
            self.assertIn('Selected ID: 130', text)
            self.assertIn('Home/End', text)
            self.assertEqual(len(text.rstrip('\n').splitlines()), height)
        self.assertEqual(nav.selected_id, 130)

    def test_selected_running_row_is_literal_and_reverse_styled(self):
        running = rows(1, 30)
        running[-1]['name'] = '[red]literal\nname'
        nav = Navigation()
        nav.sync(running, [])
        nav.handle_key('end')
        layout = tui.generate_layout('RUNNING', running, [], navigation=nav, height=25)
        table = layout.children[1].renderable.renderable
        self.assertEqual(table.rows[-1].style, 'bold reverse')
        text = self.render(nav, running, [], 25)
        self.assertIn('[red]literal name', text)
        self.assertIn('Selected ID: 30', text)

    def test_failed_poll_does_not_erase_selection_and_tiny_terminal_has_guidance(self):
        nav = Navigation()
        running = rows(1, 3)
        nav.sync(running, [])
        nav.handle_key('j')
        tui.generate_layout('ERROR', [], [], navigation=nav, height=25)
        self.assertEqual(nav.selected_id, 2)
        self.render(nav, list(reversed(running)), [], 25)
        self.assertEqual(nav.selected_id, 2)
        self.assertIn('at least 18 rows', self.render(nav, running, [], 12))

    def test_tui_query_requests_all_row_ids_but_no_diagnostic_payloads(self):
        self.assertIs(TUI_LINK_STATE_QUERY['uuid'], True)
        self.assertEqual(TUI_LINK_STATE_QUERY['maxResults'], -1)
        for key in ('advancedStatus', 'url', 'password'):
            self.assertNotIn(key, TUI_LINK_STATE_QUERY)

    def test_navigation_renders_immediately_without_polling_or_toggling(self):
        client = MagicMock()
        client.settings = SimpleNamespace(refresh_rate=1)
        client.fetch_stats.return_value = ('STOPPED', rows(1, 3), [])
        nav, views = Navigation(), []
        now = [0.0]
        keys = iter(['j', 'end'])

        def get_key():
            try:
                return next(keys)
            except StopIteration:
                raise KeyboardInterrupt

        def render(snapshot, status):
            nav.sync(snapshot.running_links, snapshot.enabled_unfinished_links)
            views.append(nav.selected_id)

        with self.assertRaises(KeyboardInterrupt):
            run_loop(client, get_key=get_key, render=render, clock=lambda: now[0],
                     sleep=lambda seconds: now.__setitem__(0, now[0] + seconds), handle_key=nav.handle_key)
        self.assertEqual(views, [None, 1, 2, 3])
        client.fetch_stats.assert_called_once()
        client.toggle_state.assert_not_called()


class ReviewRegressionTests(unittest.TestCase):
    def test_escape_timeout_and_controls_preserve_next_normal_command(self):
        now = [0.0]
        decoder = KeyDecoder(clock=lambda: now[0])
        self.assertEqual(decoder.feed('\x1b'), [])
        self.assertEqual(decoder.feed('s'), ['s'])
        self.assertEqual(decoder.feed('\x1b['), [])
        now[0] = 0.2
        self.assertEqual(decoder.feed('j'), ['j'])
        self.assertEqual(decoder.feed('\x1b[\t'), ['\t'])
        self.assertEqual(decoder.feed('\x1b[\x1b[B'), ['down'])
        self.assertEqual(decoder.feed('\x1b[\x03'), ['\x03'])
        self.assertEqual(decoder.feed('\x1b[' + '9' * 40 + 's'), [])
        self.assertEqual(decoder.feed('s'), ['s'])

    def test_posix_input_failure_and_eof_are_reported(self):
        from jdsh.errors import ServiceError
        keyboard = tui.KeyboardInput()
        with patch.object(tui, 'termios', object()), patch.object(tui.select, 'select', return_value=([0], [], [])):
            for response in (OSError('closed'), b''):
                with patch.object(tui.os, 'read', side_effect=response if isinstance(response, OSError) else None,
                                  return_value=response):
                    with self.assertRaisesRegex(ServiceError, 'Terminal input'):
                        keyboard.get_key()
        with patch.object(tui, 'termios', None), patch.object(tui, 'msvcrt', None):
            self.assertIsNone(keyboard.get_key())

    def test_windows_unknown_extended_key_is_not_a_normal_command(self):
        api = MagicMock()
        api.kbhit.return_value = True
        api.getwch.side_effect = ['\xe0', 's', 's']
        with patch.object(tui, 'termios', None), patch.object(tui, 'msvcrt', api):
            keyboard = tui.KeyboardInput()
            self.assertIsNone(keyboard.get_key())
            self.assertIsNone(keyboard.get_key())
            self.assertEqual(keyboard.get_key(), 's')

    def test_tiny_height_preserves_scroll_offsets_and_does_not_build_tables(self):
        nav = Navigation()
        nav.sync(rows(1, 40), [])
        nav.resize((10, 2))
        nav.handle_key('end')
        old = (nav.capacity[:], nav.offsets[:], nav.indices[:], nav.selected_id)
        with patch.object(tui, 'Table', side_effect=AssertionError('no table construction')):
            tui.generate_layout('STOPPED', rows(1, 40), [], navigation=nav, height=12)
        self.assertEqual(old, (nav.capacity, nav.offsets, nav.indices, nav.selected_id))

    def test_error_layout_hides_stale_rows_without_mutating_saved_selection(self):
        nav = Navigation()
        nav.sync(rows(1, 20), [])
        nav.handle_key('end')
        output = io.StringIO()
        Console(file=output, width=100, height=25).print(tui.generate_layout(
            'ERROR', [], [], navigation=nav, height=25, override_status='ERROR: offline'))
        self.assertIn('ERROR: offline', output.getvalue())
        self.assertIn('Selected ID: -', output.getvalue())
        self.assertNotIn('link-20', output.getvalue())
        self.assertEqual(nav.selected_id, 20)

    def test_inactive_pane_remembers_id_across_reordering(self):
        nav = Navigation()
        running, waiting = rows(1, 4), rows(101, 4)
        nav.sync(running, waiting)
        nav.handle_key('\t')
        nav.handle_key('j')
        self.assertEqual(nav.selected_id, 102)
        nav.handle_key('\t')
        nav.sync(running, list(reversed(waiting)))
        nav.handle_key('\t')
        self.assertEqual(nav.selected_id, 102)
        self.assertEqual(nav.indices[1], 2)

    def test_80_column_long_ids_and_japanese_names_keep_visible_rows(self):
        from rich.cells import cell_len
        running = rows(1234567890123000, 30)
        for row in running:
            row['name'] = '日本語の長いファイル名' * 10
        nav = Navigation()
        nav.sync(running, [])
        nav.handle_key('end')
        output = io.StringIO()
        Console(file=output, width=80, height=18).print(tui.generate_layout(
            'RUNNING', running, [], navigation=nav, width=80, height=18))
        text = output.getvalue()
        self.assertIn('日本語', text)
        self.assertIn('Progress', text)
        self.assertIn('Selected ID: 1234567890123029', text)
        self.assertIn('...0123029', text)
        self.assertTrue(all(cell_len(line) <= 80 for line in text.splitlines()))
        self.assertEqual(len(text.rstrip('\n').splitlines()), 18)

    def test_resize_redraws_before_next_poll_without_key_input(self):
        console = Console(file=io.StringIO(), width=100, height=40)
        client = MagicMock()
        client.settings = SimpleNamespace(refresh_rate=60)
        client.fetch_stats.return_value = ('STOPPED', rows(1, 40), [])
        keyboard, live = MagicMock(), MagicMock()
        live.__enter__.return_value = live
        count, now = [0], [0.0]

        def get_key():
            count[0] += 1
            if count[0] == 1:
                return 'end'
            if count[0] == 2:
                console.height = 18
                return None
            raise KeyboardInterrupt

        keyboard.__enter__.return_value.get_key.side_effect = get_key
        with patch.object(tui, 'Live', return_value=live), patch.object(console, 'clear'):
            tui.run(client, console=console, keyboard=keyboard, clock=lambda: now[0],
                    sleep=lambda value: now.__setitem__(0, now[0] + value))
        client.fetch_stats.assert_called_once()
        client.toggle_state.assert_not_called()
        self.assertEqual(live.update.call_count, 4)  # loading, snapshot, End, resize
        output = io.StringIO()
        Console(file=output, width=100, height=18).print(live.update.call_args.args[0])
        self.assertIn('link-40', output.getvalue())
        self.assertIn('Selected ID: 40', output.getvalue())

    def test_operation_errors_allow_navigation_but_poll_errors_block_it(self):
        from jdsh.errors import ServiceError, StatsError
        from jdsh.tui_runtime import DashboardController
        client = MagicMock()
        client.fetch_stats.return_value = ('STOPPED', rows(1, 3), [])
        controller = DashboardController(client, lambda: 0)
        controller.poll()
        client.toggle_state.side_effect = ServiceError('denied')
        controller.toggle()
        self.assertEqual(controller.display_error, 'ERROR: denied')
        self.assertTrue(controller.can_navigate)
        client.fetch_stats.side_effect = StatsError('offline')
        controller.poll()
        self.assertFalse(controller.can_navigate)

    def test_buffered_navigation_does_not_sleep_per_key(self):
        client = MagicMock()
        client.settings = SimpleNamespace(refresh_rate=60)
        client.fetch_stats.return_value = ('STOPPED', rows(1, 100), [])
        nav, keys = Navigation(), iter(['j'] * 30)
        sleep = MagicMock()

        def get_key():
            try:
                return next(keys)
            except StopIteration:
                raise KeyboardInterrupt

        def render(snapshot, override):
            nav.sync(snapshot.running_links, snapshot.enabled_unfinished_links)

        with self.assertRaises(KeyboardInterrupt):
            run_loop(client, get_key=get_key, render=render, clock=lambda: 0,
                     sleep=sleep, handle_key=nav.handle_key)
        self.assertEqual(nav.selected_id, 31)
        sleep.assert_not_called()
        client.fetch_stats.assert_called_once()

    def test_poll_error_never_calls_navigation_handler(self):
        from jdsh.errors import StatsError
        client = MagicMock()
        client.settings = SimpleNamespace(refresh_rate=60)
        client.fetch_stats.side_effect = StatsError('offline')
        keys, handler = iter(['j']), MagicMock()

        def get_key():
            try:
                return next(keys)
            except StopIteration:
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            run_loop(client, get_key=get_key, render=MagicMock(), clock=lambda: 0,
                     sleep=MagicMock(), handle_key=handler)
        handler.assert_not_called()
