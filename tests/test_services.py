"""Verify reusable services independently of CLI output and real-time waiting."""

import contextlib
import io
import unittest
from unittest.mock import MagicMock

from jdsh import services
from jdsh.client import DOWNLOAD_LINK_STATE_QUERY


class DownloadServiceTests(unittest.TestCase):
    @staticmethod
    def link(status_id):
        return {
            "uuid": 123,
            "name": "file.zip",
            "advancedStatus": {"AvailableStatus": {"id": status_id}},
        }

    def test_show_returns_raw_unknown_fields_without_terminal_output(self):
        device = MagicMock()
        link = {"uuid": 123, "name": "file.zip", "futureField": {"value": None}}
        device.downloads.query_links.return_value = [link]
        device.action.return_value = {}
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            payload = services.show_download(device, 123)
        self.assertIs(payload["link"], link)
        self.assertEqual(payload["link"]["futureField"], {"value": None})
        self.assertIsNone(payload["package"])
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("linkUUIDs", DOWNLOAD_LINK_STATE_QUERY)

    def test_missing_selection_raises_service_error_without_mutation(self):
        for operation, error in (
            (services.show_download, services.ShowError),
            (services.explain_download, services.WhyError),
            (services.check_download, services.CheckError),
        ):
            with self.subTest(operation=operation.__name__):
                device = MagicMock()
                device.downloads.query_links.return_value = []
                with self.assertRaisesRegex(error, "Download link ID not found: 123"):
                    operation(device, 123)
                device.action.assert_not_called()

    def test_check_uses_injected_clock_and_sleep_for_same_result(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [self.link("TRUE")]
        moments = iter([0.0, 0.1, 1.1])
        pauses = []
        result = services.check_download(device, 123, clock=lambda: next(moments), sleep=pauses.append)
        self.assertEqual(result["availableStatus"], {"id": "TRUE"})
        self.assertEqual(pauses, [services.CHECK_POLL_INTERVAL_SECONDS])
        device.action.assert_called_once_with("/downloadsV2/startOnlineStatusCheck", [[123], []])

    def test_check_times_out_using_injected_clock(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [self.link("UNCHECKED")]
        moments = iter([0.0, services.CHECK_TIMEOUT_SECONDS])
        pauses = []
        with self.assertRaisesRegex(services.CheckError, "Online status check timed out"):
            services.check_download(device, 123, clock=lambda: next(moments), sleep=pauses.append)
        self.assertEqual(pauses, [])

    def test_check_all_deduplicates_ids_and_queues_one_request(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [{"uuid": 123}, {"uuid": 123}, {}, {"uuid": 456}]
        self.assertEqual(services.check_all_downloads(device), {"started": True, "linkCount": 2})
        device.action.assert_called_once_with("/downloadsV2/startOnlineStatusCheck", [[123, 456], []])


if __name__ == "__main__":
    unittest.main()
