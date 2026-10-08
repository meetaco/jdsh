"""Completion-time sorting for finished download history."""

import unittest
from unittest.mock import MagicMock

from jdsh import arguments, services
from jdsh.client import LIST_LINK_STATE_QUERY
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
        ]
        result = sort_rows(rows, sort="finished", reverse=True)
        self.assertEqual([row["uuid"] for row in result], [2, 4, 1, 3, 5])

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
            dict(LIST_LINK_STATE_QUERY, startAt=0, maxResults=-1),
        ])
        self.assertIs(LIST_LINK_STATE_QUERY["finishedDate"], True)

    def test_package_finished_sort_uses_latest_matched_completion(self):
        rows = [
            link(1, finished_date=1000, package_uuid=10),
            link(2, finished_date=3000, package_uuid=10),
            link(3, finished_date=2000, package_uuid=20),
        ]
        packages = summarize_packages(rows, rows, {10: "a", 20: "b"})
        result = sort_rows(packages, sort="finished", reverse=True, packages=True)
        self.assertEqual([row["uuid"] for row in result], [10, 20])
        self.assertEqual(result[0]["finishedDate"], 3000)


if __name__ == "__main__":
    unittest.main()
