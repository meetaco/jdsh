import copy
import unittest

from jdsh import stats, utils


class TransferStatsTests(unittest.TestCase):
    @staticmethod
    def link(**values):
        return {'bytesLoaded': 25, 'bytesTotal': 100, 'speed': 10, 'eta': 7, **values}

    def test_known_values_produce_progress_and_totals(self):
        links = [self.link(), self.link(bytesLoaded=10, bytesTotal=50, speed=5)]
        progress = stats.transfer_progress(links[0])
        self.assertEqual((progress.percent, progress.remaining), (25.0, 75))
        self.assertEqual(stats.summarize_transfers(links), stats.TransferSummary(15, 35, 150, 115))

    def test_missing_total_does_not_turn_into_one_byte(self):
        progress = stats.transfer_progress({'bytesLoaded': 0})
        self.assertIsNone(progress.total)
        self.assertIsNone(progress.percent)
        self.assertEqual(utils.human_size(progress.total), 'null')
        self.assertEqual(utils.human_percent(progress.percent), '-')

    def test_zero_total_is_preserved_without_division(self):
        progress = stats.transfer_progress(self.link(bytesLoaded=0, bytesTotal=0))
        self.assertEqual(progress.total, 0)
        self.assertEqual(progress.remaining, 0)
        self.assertIsNone(progress.percent)
        self.assertEqual(utils.human_size(progress.total), '0 B')

    def test_unknown_loaded_is_not_assumed_zero(self):
        progress = stats.transfer_progress(self.link(bytesLoaded=None))
        self.assertIsNone(progress.loaded)
        self.assertIsNone(progress.percent)
        self.assertIsNone(progress.remaining)

    def test_invalid_numeric_values_are_unknown_and_raw_data_is_unchanged(self):
        for value in (None, -1, '100', True, float('nan'), float('inf'), float('-inf')):
            with self.subTest(value=value):
                link = self.link(bytesTotal=value)
                progress = stats.transfer_progress(link)
                self.assertIsNone(progress.total)
                self.assertIs(link['bytesTotal'], value)
                self.assertEqual(utils.human_size(value), 'null')
                self.assertEqual(utils.human_eta(value), '-')

    def test_unknown_field_does_not_hide_other_known_aggregate_fields(self):
        result = stats.summarize_transfers([self.link(), self.link(bytesTotal=None, speed=None)])
        self.assertIsNone(result.speed)
        self.assertIsNone(result.total)
        self.assertIsNone(result.remaining)
        self.assertEqual(result.loaded, 50)

    def test_empty_selection_has_known_zero_totals(self):
        self.assertEqual(stats.summarize_transfers([]), stats.TransferSummary(0, 0, 0, 0))

    def test_overrun_clamps_display_and_does_not_cancel_other_links_remaining(self):
        links = [self.link(bytesLoaded=150), self.link(bytesLoaded=0)]
        original = copy.deepcopy(links)
        self.assertEqual(stats.transfer_progress(links[0]).percent, 100.0)
        self.assertEqual(stats.summarize_transfers(links).remaining, 100)
        self.assertEqual(links, original)
        self.assertEqual(links[0]['bytesLoaded'], 150)

    def test_overflowed_float_aggregate_is_unknown(self):
        self.assertIsNone(stats.summarize_transfers([self.link(speed=1e308), self.link(speed=1e308)]).speed)

    def test_partition_keeps_raw_objects_and_excludes_finished(self):
        links = [{'running': True, 'enabled': False}, {'running': False, 'enabled': True},
                 {'running': True, 'finished': True}, {'enabled': False}, {}]
        original = copy.deepcopy(links)
        running, unfinished = stats.partition_links(links)
        self.assertEqual(running, links[:1])
        self.assertEqual(unfinished, links[1:2])
        self.assertIs(running[0], links[0])
        self.assertIs(unfinished[0], links[1])
        self.assertEqual(links, original)
