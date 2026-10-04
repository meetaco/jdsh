"""Queue browsing preserves raw state and summarizes only matched links."""

import io
import unittest
from copy import deepcopy
from unittest.mock import MagicMock, patch

from rich.console import Console

from jdsh import arguments, cli, services
from jdsh.client import LIST_LINK_STATE_QUERY, DOWNLOAD_LINK_STATE_QUERY
from jdsh.queue_view import filter_links, sort_rows, summarize_packages


def link(uuid, name="file.zip", **kwargs):
    return dict(uuid=uuid, name=name, **kwargs)


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.links = [
            link(1, "Archive.ZIP", host="Example.COM", enabled=True),
            link(2, "archive.part2", host="other.com", running=True),
            link(3, "notes.txt", host="example.com", enabled=False),
        ]

    def test_filter_intersection_and_repeated_alternatives(self):
        result = filter_links(self.links, search="ARCHIVE", states=["waiting", "running"],
                              hosts=["EXAMPLE.com", "other.com"])
        self.assertEqual([item['uuid'] for item in result], [1, 2])
        self.assertEqual(filter_links(self.links, search="archive", hosts=["example.com"]), [self.links[0]])

    def test_host_is_exact_not_substring(self):
        self.assertEqual(filter_links(self.links, hosts=["example"]), [])

    def test_unknown_fields_and_unicode_search(self):
        rows = [link(1, "Straße"), link(2, None)]
        self.assertEqual(filter_links(rows, search="STRASSE"), [rows[0]])
        self.assertEqual(filter_links(rows, states=["UNKNOWN"]), rows)
        self.assertEqual(filter_links(rows, hosts=["example.com"]), [])

    def test_state_uses_diagnostic_precedence(self):
        rows = [link(1, running=True, finished=True),
                link(2, advancedStatus={"ConditionalSkipReason": {"id": "WAIT"}}),
                link(3, advancedStatus={"AvailableStatus": {"id": "FALSE"}})]
        for state, expected in (("RUNNING", 1), ("WAITING", 2), ("OFFLINE", 3)):
            self.assertEqual(filter_links(rows, states=[state])[0]['uuid'], expected)

    def test_filters_do_not_modify_raw_data(self):
        before = deepcopy(self.links)
        result = filter_links(self.links, search="archive")
        self.assertIs(result[0], self.links[0])
        self.assertEqual(self.links, before)
        self.assertIs(filter_links(self.links), self.links)


class SortTests(unittest.TestCase):
    def test_numeric_id_sort(self):
        rows = [link(10), link(2), link(None)]
        self.assertEqual([row['uuid'] for row in sort_rows(rows, sort="id")], [2, 10, None])

    def test_name_sort_is_case_insensitive_and_stable(self):
        rows = [link(1, "z"), link(2, "A"), link(3, "a"), link(4, None)]
        self.assertEqual([row['uuid'] for row in sort_rows(rows, sort="name")], [2, 3, 1, 4])
        self.assertEqual([row['uuid'] for row in sort_rows(rows, sort="name", reverse=True)], [1, 2, 3, 4])

    def test_unknown_sizes_stay_last_both_directions(self):
        rows = [link(1, bytesTotal=None), link(2, bytesTotal=0), link(3, bytesTotal=100),
                link(4, bytesTotal=-1), link(5, bytesTotal=float('nan')),
                link(6, bytesTotal=True)]
        for reverse, expected in ((False, [2, 3, 1, 4, 5, 6]), (True, [3, 2, 1, 4, 5, 6])):
            self.assertEqual([row['uuid'] for row in sort_rows(rows, sort="size", reverse=reverse)], expected)

    def test_progress_uses_ratio_and_zero_total_is_unknown(self):
        rows = [link(1, bytesLoaded=20, bytesTotal=100),
                link(2, bytesLoaded=5, bytesTotal=10), link(3, bytesLoaded=0, bytesTotal=0)]
        self.assertEqual([row['uuid'] for row in sort_rows(rows, sort="progress", reverse=True)], [2, 1, 3])

    def test_sort_preserves_input_and_default_api_order(self):
        rows = [link(2, host="z"), link(1, host="A")]
        before = deepcopy(rows)
        self.assertIs(sort_rows(rows), rows)
        self.assertEqual(sort_rows(rows, sort="host"), [rows[1], rows[0]])
        self.assertEqual(rows, before)


class PackageTests(unittest.TestCase):
    def test_matched_counts_sizes_states_and_unknown_parent_are_preserved(self):
        rows = [link(1, packageUUID=10, host="a", bytesLoaded=10, bytesTotal=100, running=True),
                link(2, packageUUID=10, host="b", bytesLoaded=20, bytesTotal=200, enabled=True),
                link(3, packageUUID=20, bytesLoaded=None, bytesTotal=-1),
                link(4, bytesLoaded=0, bytesTotal=0)]
        before = deepcopy(rows)
        result = summarize_packages(rows, [rows[0], rows[2], rows[3]], [{"uuid": 10, "name": "Archive"}])
        self.assertEqual(result[0], {
            "uuid": 10, "name": "Archive", "matchedCount": 1, "linkCount": 2,
            "bytesLoaded": 10, "bytesTotal": 100, "states": {"RUNNING": 1}, "hosts": ["a"],
        })
        self.assertIsNone(result[1]['name'])
        self.assertIsNone(result[1]['bytesTotal'])
        self.assertIsNone(result[2]['uuid'])
        self.assertEqual(result[2]['bytesTotal'], 0)
        self.assertEqual(rows, before)

    def test_unknown_member_makes_aggregate_unknown(self):
        rows = [link(1, packageUUID=10, bytesLoaded=1, bytesTotal=100), link(2, packageUUID=10)]
        result = summarize_packages(rows, rows, [])[0]
        self.assertIsNone(result['bytesTotal'])
        self.assertIsNone(result['bytesLoaded'])

    def test_package_name_search_intersects_with_link_state(self):
        device = MagicMock()
        rows = [link(1, "part1", packageUUID=10, running=True),
                link(2, "part2", packageUUID=10, enabled=True),
                link(3, "ARCHIVE-file", packageUUID=20, enabled=True)]
        device.downloads.query_links.return_value = rows
        device.downloads.query_packages.return_value = [{"uuid": 10, "name": "Archive"}]
        result = services.list_download_packages(device, search="ARCHIVE", states=["WAITING"])
        self.assertEqual([(row['uuid'], row['matchedCount'], row['linkCount']) for row in result], [(10, 1, 2), (20, 1, 1)])
        device.downloads.query_packages.assert_called_once_with([{"startAt": 0, "maxResults": -1}])
        device.downloads.query_links.assert_called_once_with([dict(LIST_LINK_STATE_QUERY, startAt=0, maxResults=-1)])

    def test_package_sort_uses_aggregate_not_first_child(self):
        rows = [link(1, packageUUID=10, bytesTotal=10), link(2, packageUUID=10, bytesTotal=100),
                link(3, packageUUID=20, bytesTotal=50)]
        result = sort_rows(summarize_packages(rows, rows, []), sort="size")
        self.assertEqual([row['uuid'] for row in result], [20, 10])

    def test_empty_queue_does_not_query_metadata(self):
        device = MagicMock()
        device.downloads.query_links.return_value = []
        self.assertEqual(services.list_download_packages(device), [])
        device.downloads.query_packages.assert_not_called()


class BrowseCLITests(unittest.TestCase):
    def test_parser_combines_options_for_both_aliases(self):
        for command in ('list', 'ls'):
            args = arguments.parse_args([command, '--search', 'archive', '--state', 'waiting',
                                         '--state', 'running', '--host', 'a', '--host', 'b',
                                         '--sort', 'size', '--reverse', '--packages'])
            self.assertEqual(args.state, ['WAITING', 'RUNNING'])
            self.assertEqual(args.host, ['a', 'b'])
            self.assertTrue(args.packages)

    def test_invalid_options_exit_before_settings_or_api(self):
        for argv in (['ls', '--reverse'], ['ls', '--packages', '-d'],
                     ['ls', '--sort', 'bad'], ['ls', '--state', 'bad']):
            with self.subTest(argv=argv), patch.object(cli.config, 'load_settings') as settings, \
                 patch.object(cli, 'JDClient') as client, patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as caught:
                    cli.main(argv)
                self.assertEqual(caught.exception.code, 2)
                settings.assert_not_called()
                client.assert_not_called()

    def test_filtered_detail_keeps_raw_fields_and_requests_all_links(self):
        device = MagicMock()
        row = link(1, "Archive", futureField={"value": 7})
        device.downloads.query_links.return_value = [row, link(2, "Other")]
        output = io.StringIO()
        cli.cmd_list(device, arguments.parse_args(['ls', '-d', '--search', 'archive']),
                     console=Console(file=output, width=140))
        self.assertIn('futureField', output.getvalue())
        self.assertNotIn('Other', output.getvalue())
        device.downloads.query_links.assert_called_once_with([dict(DOWNLOAD_LINK_STATE_QUERY, startAt=0, maxResults=-1)])
        device.downloads.query_packages.assert_not_called()

    def test_no_match_message(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [link(1)]
        output = io.StringIO()
        cli.cmd_list(device, arguments.parse_args(['ls', '--search', 'absent']), console=Console(file=output))
        self.assertIn('No downloads match the filters.', output.getvalue())
        self.assertNotIn('queue is empty', output.getvalue())

    def test_packages_render_literal_names_and_matched_counts(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [
            link(1, packageUUID=10, host='a', running=True, bytesLoaded=10, bytesTotal=100),
            link(2, packageUUID=10, enabled=True),
        ]
        device.downloads.query_packages.return_value = [{'uuid': 10, 'name': '[red]Archive'}]
        output = io.StringIO()
        cli.cmd_list(device, arguments.parse_args(['ls', '--packages', '--state', 'running']),
                     console=Console(file=output, width=180))
        for expected in ('[red]Archive', '1/2', 'RUNNING: 1', '10.00 B/100.00 B'):
            self.assertIn(expected, output.getvalue())

    def test_package_metadata_failure_is_reported_without_success_output(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [link(1, packageUUID=10)]
        device.downloads.query_packages.side_effect = RuntimeError('metadata unavailable')
        with patch('sys.stderr', new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as caught:
                cli._execute(cli.cmd_list, device, arguments.parse_args(['ls', '--packages']))
        self.assertEqual(caught.exception.code, 1)
        self.assertIn('metadata unavailable', stderr.getvalue())
