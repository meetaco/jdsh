"""Completion-time sorting for finished download history."""

import unittest
from unittest.mock import MagicMock

from jdsh import arguments, services
from jdsh.client import DOWNLOAD_LINK_STATE_QUERY, LIST_LINK_STATE_QUERY
from jdsh.queue_view import sort_rows, summarize_packages


def link(uuid, *, finished=True, finished_date=None, package_uuid=None):
    row = {"uuid": uuid, "name": f"file-{uuid}", "finished": finished}
    if finished_date is not None:
        row["finishedDate"] = finished_date
    if package_uuid is not None:
        row["packageUUID"] = package_uuid
    return row


class FinishedSortTests(unittest.TestCase):
    def test_cli_accepts_finished_descending_sort(self):
        args = arguments.parse_args([
            "ls", "--state", "FINISHED", "--sort", "finished", "--reverse",
        ])
        self.assertEqual(args.state, ["FINISHED"])
        self.assertEqual(args.sort, "finished")
        self.assertTrue(args.reverse)

    def test_finished_sort_is_numeric_and_unknown_dates_stay_last(self):
        rows = [
            link(1, finished_date=1000),
            link(2, finished_date=3000),
            link(3),
            link(4, finished_date=2000),
            link(5, finished_date=-1),
            link(6, finished_date=0),
            link(7, finished_date="3000"),
            link(8, finished_date=float("nan")),
            link(9, finished_date=float("inf")),
            link(10, finished_date=True),
            link(11, finished_date=2000),
        ]
        for reverse, known_ids in ((False, [1, 4, 11, 2]), (True, [2, 4, 11, 1])):
            with self.subTest(reverse=reverse):
                result = sort_rows(rows, sort="finished", reverse=reverse)
                self.assertEqual(
                    [row["uuid"] for row in result],
                    known_ids + [3, 5, 6, 7, 8, 9, 10],
                )

    def test_finished_filter_and_sort_return_latest_first(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [
            link(1, finished_date=1000),
            link(2, finished=False, finished_date=4000),
            link(3, finished_date=3000),
            link(4, finished_date=2000),
        ]

        result = services.list_downloads(
            device, states=["FINISHED"], sort="finished", reverse=True,
        )

        self.assertEqual([row["uuid"] for row in result], [3, 4, 1])
        device.downloads.query_links.assert_called_once_with([
            dict(LIST_LINK_STATE_QUERY, finishedDate=True, startAt=0, maxResults=-1),
        ])

    def test_completion_query_is_requested_only_when_needed(self):
        for packages in (False, True):
            for sort in (None, "name", "finished"):
                with self.subTest(packages=packages, sort=sort):
                    device = MagicMock()
                    device.downloads.query_links.return_value = []
                    operation = (services.list_download_packages if packages
                                 else services.list_downloads)
                    operation(device, sort=sort)
                    query = device.downloads.query_links.call_args.args[0][0]
                    if sort == "finished":
                        self.assertIs(query["finishedDate"], True)
                    else:
                        self.assertNotIn("finishedDate", query)
        self.assertNotIn("finishedDate", LIST_LINK_STATE_QUERY)

    def test_diagnostic_query_preserves_completion_time(self):
        device = MagicMock()
        device.downloads.query_links.return_value = []
        services.list_downloads(device, detail=True)
        query = device.downloads.query_links.call_args.args[0][0]
        self.assertIs(query["finishedDate"], True)
        self.assertIs(DOWNLOAD_LINK_STATE_QUERY["finishedDate"], True)

    def test_package_service_filters_before_aggregating_completion_time(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [
            link(1, finished_date=1000, package_uuid=10),
            link(2, finished_date=2000, package_uuid=20),
            link(3, finished=False, finished_date=9000, package_uuid=10),
            link(4, package_uuid=30),
        ]
        device.downloads.query_packages.return_value = [
            {"uuid": 10, "name": "a"}, {"uuid": 20, "name": "b"},
            {"uuid": 30, "name": "c"},
        ]
        result = services.list_download_packages(
            device, states=["FINISHED"], sort="finished", reverse=True,
        )
        self.assertEqual([row["uuid"] for row in result], [20, 10, 30])
        self.assertEqual(result[1]["finishedDate"], 1000)
        self.assertEqual(result[1]["matchedCount"], 1)
        self.assertEqual(result[1]["linkCount"], 2)
        self.assertNotIn("finishedDate", result[2])
        device.downloads.query_links.assert_called_once_with([
            dict(LIST_LINK_STATE_QUERY, finishedDate=True, startAt=0, maxResults=-1),
        ])

    def test_package_finished_sort_uses_latest_matched_completion(self):
        rows = [
            link(1, finished_date=1000, package_uuid=10),
            link(2, finished_date=3000, package_uuid=10),
            link(3, finished_date=2000, package_uuid=20),
            link(4, package_uuid=30),
            link(5, finished_date=0, package_uuid=30),
            link(6, finished_date=-1, package_uuid=30),
            link(7, finished_date=9000, package_uuid=20),
        ]
        packages = summarize_packages(rows, rows[:-1], {10: "a", 20: "b", 30: "c"})
        self.assertEqual(packages[0]["finishedDate"], 3000)
        self.assertEqual(packages[1]["finishedDate"], 2000)
        self.assertNotIn("finishedDate", packages[2])
        self.assertEqual(packages[1]["matchedCount"], 1)
        self.assertEqual(packages[1]["linkCount"], 2)
        for reverse, expected in ((False, [20, 10, 30]), (True, [10, 20, 30])):
            with self.subTest(reverse=reverse):
                result = sort_rows(packages, sort="finished", reverse=reverse, packages=True)
                self.assertEqual([row["uuid"] for row in result], expected)


if __name__ == "__main__":
    unittest.main()
