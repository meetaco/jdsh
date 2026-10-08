"""Completion timestamps are displayed from JD2 without keeping local history."""

import io
import os
import time
import unittest
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import MagicMock, patch

from rich.console import Console

from jdsh import arguments, cli, rendering, utils


@contextmanager
def local_timezone(value):
    try:
        with patch.dict(os.environ, {"TZ": value}):
            time.tzset()
            yield
    finally:
        time.tzset()


@unittest.skipUnless(hasattr(time, "tzset"), "requires POSIX timezone control")
class FinishedDateDisplayTests(unittest.TestCase):
    def test_epoch_milliseconds_are_formatted_in_local_time_with_offset(self):
        for zone, expected in (
            ("UTC0", "2024-01-01 00:00:00+00:00"),
            ("JST-9", "2024-01-01 09:00:00+09:00"),
        ):
            with self.subTest(zone=zone), local_timezone(zone):
                self.assertEqual(utils.human_timestamp(1704067200123), expected)

    def test_offset_tracks_daylight_saving_at_completion_time(self):
        with local_timezone("EST5EDT,M3.2.0,M11.1.0"):
            self.assertEqual(utils.human_timestamp(1704067200000),
                             "2023-12-31 19:00:00-05:00")
            self.assertEqual(utils.human_timestamp(1719792000000),
                             "2024-06-30 20:00:00-04:00")

    def test_plain_list_fetches_and_displays_completion_time_without_sort(self):
        device = MagicMock()
        row = {"uuid": 1, "name": "done.zip", "finished": True,
               "finishedDate": 1704067200000}

        def query(payload):
            # Model JD2 returning the timestamp only when explicitly requested.
            return [{key: value for key, value in row.items() if payload[0].get(key)}]

        device.downloads.query_links.side_effect = query
        output = io.StringIO()
        with local_timezone("JST-9"):
            cli.cmd_list(device, arguments.parse_args(["ls"]),
                         console=Console(file=output, width=240))
        self.assertIn("Finished at", output.getvalue())
        self.assertIn("2024-01-01 09:00:00+09:00", output.getvalue())
        self.assertIn("done.zip", output.getvalue())

    def test_package_column_uses_latest_matched_completion_even_without_sort(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [
            {"uuid": 1, "name": "done.zip", "packageUUID": 10,
             "finished": True, "finishedDate": 1704067200000},
            {"uuid": 2, "name": "done2.zip", "packageUUID": 10,
             "finished": True, "finishedDate": 1704153600000},
            {"uuid": 3, "name": "unfinished.zip", "packageUUID": 10,
             "finished": False, "finishedDate": 1704240000000},
        ]
        device.downloads.query_packages.return_value = [{"uuid": 10, "name": "archive"}]
        output = io.StringIO()
        with local_timezone("UTC0"):
            cli.cmd_list(device, arguments.parse_args(["ls", "--packages", "--state", "finished"]),
                         console=Console(file=output, width=240))
        self.assertIs(device.downloads.query_links.call_args.args[0][0]["finishedDate"], True)
        self.assertIn("Finished at", output.getvalue())
        self.assertIn("2024-01-02 00:00:00+00:00", output.getvalue())
        self.assertNotIn("2024-01-03", output.getvalue())

    def test_detail_output_keeps_raw_timestamp_and_input_is_unchanged(self):
        rows = [{"uuid": 1, "name": "done.zip", "finished": True,
                 "finishedDate": 1704067200000}]
        before = deepcopy(rows)
        output = io.StringIO()
        with local_timezone("UTC0"):
            rendering.render_list(rows, detail=True, console=Console(file=output, width=240))
        self.assertIn("finishedDate: 1704067200000", output.getvalue())
        self.assertEqual(rows, before)


class UnknownFinishedDateTests(unittest.TestCase):
    def test_unknown_and_out_of_range_dates_display_dash(self):
        for value in (None, 0, -1, "1704067200000", True, float("nan"),
                      float("inf"), -float("inf"), 10**400, 1e100):
            with self.subTest(value=value):
                self.assertEqual(utils.human_timestamp(value), "-")

    def test_missing_link_and_package_dates_render_dash(self):
        console = MagicMock()
        rendering.render_list([{"uuid": 1, "name": "waiting.zip"}], console=console)
        table = console.print.call_args.args[0]
        column = next(column for column in table.columns if column.header == "Finished at")
        self.assertEqual(list(column.cells), ["-"])
        console.reset_mock()
        rendering.render_packages([{
            "uuid": 10, "name": "waiting", "matchedCount": 1, "linkCount": 1,
            "bytesLoaded": None, "bytesTotal": None, "states": {}, "hosts": [],
        }], console=console)
        table = console.print.call_args.args[0]
        column = next(column for column in table.columns if column.header == "Finished at")
        self.assertEqual(list(column.cells), ["-"])


if __name__ == "__main__":
    unittest.main()
