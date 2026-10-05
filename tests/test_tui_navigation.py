"""Navigation boundaries, streamed keys, and actual Rich viewports without a JD."""

import io
import os
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
