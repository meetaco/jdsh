import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.cells import cell_len
from rich.console import Console

from jdsh import tui
from jdsh.errors import StatsError
from jdsh.tui_navigation import Navigation, KeyDecoder
from jdsh.tui_search import Search


def row(link_id, name):
    return {'uuid': link_id, 'name': name, 'running': False, 'enabled': True,
            'bytesLoaded': 1, 'bytesTotal': 10, 'speed': 2}


class SearchTests(unittest.TestCase):
    def test_apply_cancel_backspace_and_clear(self):
        search = Search()
        search.begin()
        for key in ['A', 'B', '\x7f', '日', '\r']:
            search.handle_key(key)
        self.assertEqual(search.query, 'A日')
        search.begin()
        search.handle_key('\x15')
        search.handle_key('x')
        search.handle_key('escape')
        self.assertEqual(search.query, 'A日')
        search.begin()
        search.handle_key('\x15')
        search.handle_key('\n')
        self.assertIsNone(search.query)
        self.assertFalse(search.editing)

    def test_unicode_casefold_substring_and_unmodified_rows(self):
        search = Search()
        links = [row(1, 'Straße 日本語.zip'), row(2, 'OTHER')]
        search.query = 'STRASSE'
        self.assertEqual(search.filter(links), [links[0]])
        search.query = '日本語'
        self.assertIs(search.filter(links)[0], links[0])
        self.assertEqual(len(links), 2)
        search.query = 'missing'
        self.assertEqual(search.filter(links), [])

    def test_draft_bounded_and_control_keys_do_not_become_commands(self):
        search = Search()
        search.begin()
        self.assertFalse(search.handle_key(None))
        for key in ['s', 'd', 'q', 'up', '\t', '\x00'] + ['x'] * 300:
            self.assertTrue(search.handle_key(key))
        self.assertEqual(len(search.draft), 256)
        self.assertTrue(search.draft.startswith('sdq'))
        self.assertNotIn('\t', search.draft)
        self.assertIsNone(search.query)

    def test_filtered_layout_counts_selection_and_80_by_18(self):
        nav, search = Navigation(), Search()
        running = [row(1, 'one'), row(2, '[red]日本語[/red]')]
        waiting = [row(3, '日本語 waiting'), row(4, 'four')]
        nav.sync(running, waiting)
        nav.handle_key('j')
        search.query = '日本語'
        output = io.StringIO()
        Console(file=output, width=80, height=18).print(tui.generate_layout(
            'RUNNING', running, waiting, navigation=nav, search=search, width=80, height=18))
        text = output.getvalue()
        self.assertIn('Running Links (1/2 matches)', text)
        self.assertIn('Enabled Unfinished (1/2 matches)', text)
        self.assertIn('Selected ID: 2', text)
        self.assertIn('/日本語', text)
        self.assertIn('[red]', text)
        self.assertIn('Running: 2', text)  # Header totals remain global.
        self.assertEqual(len(text.rstrip('\n').splitlines()), 18)
        self.assertTrue(all(cell_len(line) <= 80 for line in text.splitlines()))
        search.query = 'nothing'
        tui.generate_layout('RUNNING', running, waiting, navigation=nav, search=search)
        self.assertIsNone(nav.selected_id)
        search.query = None
        tui.generate_layout('RUNNING', running, waiting, navigation=nav, search=search)
        self.assertEqual(len(nav.rows[0]), 2)

    def test_prompt_preserves_markup_without_interpreting_it(self):
        search = Search()
        search.begin()
        search.draft = '[red]日本語[/red]'
        output = io.StringIO()
        Console(file=output, width=80).print(search.prompt(80))
        self.assertIn('[red]', output.getvalue())
        self.assertIn('Esc Cancel', output.getvalue())
        search.draft = '日本語' * 80
        prompt = search.prompt(80).plain.splitlines()[0]
        self.assertLessEqual(cell_len(prompt), 80)
        self.assertTrue(prompt.endswith('_'))
        self.assertIn('...', prompt)

    def test_escape_timeout_and_arrow_remain_distinct(self):
        now = [0.0]
        decoder = KeyDecoder(clock=lambda: now[0])
        self.assertEqual(decoder.feed('\x1b'), [])
        now[0] = 0.2
        self.assertEqual(decoder.expire(), ['escape'])
        self.assertEqual(decoder.expire(), [])
        self.assertEqual(decoder.feed('\x1b[A'), ['up'])
        self.assertEqual(decoder.feed('\x1bx'), ['escape', 'x'])

    def test_posix_fragmented_utf8_and_idle_escape_event(self):
        keyboard = tui.KeyboardInput()
        now = [0.0]
        keyboard.decoder = KeyDecoder(clock=lambda: now[0])
        with patch.object(tui, 'termios', object()), \
             patch.object(tui.select, 'select', return_value=([0], [], [])), \
             patch.object(tui.os, 'read', side_effect=[b'\xe6', b'\x97\xa5', b'\x1b']):
            self.assertIsNone(keyboard.get_key())
            self.assertEqual(keyboard.get_key(), '日')
            self.assertIsNone(keyboard.get_key())
            now[0] = 0.2
            self.assertEqual(keyboard.get_key(), 'escape')

    def run_keys(self, keys, snapshots):
        client, keyboard, live = MagicMock(), MagicMock(), MagicMock()
        client.settings = SimpleNamespace(refresh_rate=0.1)
        client.fetch_stats.side_effect = snapshots
        live.__enter__.return_value = live
        keys = iter(keys)
        def get_key():
            try:
                return next(keys)
            except StopIteration:
                raise KeyboardInterrupt
        keyboard.__enter__.return_value.get_key.side_effect = get_key
        console = Console(file=io.StringIO(), width=80, height=18)
        now = [0.0]
        with patch.object(tui, 'Live', return_value=live), patch.object(console, 'clear'):
            tui.run(client, console=console, keyboard=keyboard, clock=lambda: now[0],
                    sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
        output = io.StringIO()
        Console(file=output, width=80, height=18).print(live.update.call_args.args[0])
        return client, output.getvalue()

    def test_input_apply_search_never_fetches_details_or_toggles(self):
        rows = [row(1, 'one'), row(2, 'sd日')]
        client, text = self.run_keys(['/', 's', 'd', '日', 'up', '\r'], [('RUNNING', rows, [])])
        client.fetch_stats.assert_called_once()
        client.toggle_state.assert_not_called()
        client.device.downloads.query_links.assert_not_called()
        self.assertIn('Selected ID: 2', text)
        self.assertIn('1/2 matches', text)

    def test_search_applies_to_new_snapshots_and_can_cancel_during_poll_failure(self):
        rows = [row(1, 'one'), row(2, 'two')]
        client, text = self.run_keys(['/', 't', '\r', None, '/', '\x15', 'escape'],
                                    [('RUNNING', rows, []), StatsError('offline')])
        self.assertEqual(client.fetch_stats.call_count, 2)
        self.assertIn('ERROR: offline', text)
        self.assertIn('/t', text)
        client.toggle_state.assert_not_called()

    def test_details_query_uses_filtered_selection(self):
        rows = [row(1, 'one'), row(2, 'two')]
        with patch('jdsh.tui_details.services.explain_download', return_value={'diagnosis': {}, 'name': 'two'}) as explain:
            client, text = self.run_keys(['/', 't', '\r', 'd', 'q'], [('RUNNING', rows, [])])
        explain.assert_called_once_with(client.device, 2)
        self.assertIn('Selected ID: 2', text)

    def test_filter_survives_reorder_and_migration(self):
        nav, search = Navigation(), Search()
        search.query = 'match'
        running = [row(1, 'match'), row(2, 'match two')]
        tui.generate_layout('RUNNING', running, [], navigation=nav, search=search)
        nav.handle_key('j')
        tui.generate_layout('RUNNING', [running[0]], [running[1]], navigation=nav, search=search)
        self.assertEqual(nav.selected_id, 2)
        self.assertEqual(nav.pane, 1)


if __name__ == '__main__':
    unittest.main()
