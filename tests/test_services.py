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

    def test_explain_preserves_controller_state_and_raw_evidence(self):
        device = MagicMock()
        link = dict(self.link("TRUE"), enabled=True, running=False, finished=False)
        device.downloads.query_links.return_value = [link]
        device.downloadcontroller.get_current_state.return_value = "STOPPED"
        payload = services.explain_download(device, 123)
        self.assertEqual(payload["controllerState"], "STOPPED")
        self.assertEqual(payload["diagnosis"]["source"], "inferred")
        self.assertIs(payload["advancedStatus"], link["advancedStatus"])

    def test_explain_controller_failure_preserves_link_diagnosis(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [self.link("FALSE")]
        device.downloadcontroller.get_current_state.side_effect = RuntimeError("unreachable")
        payload = services.explain_download(device, 123)
        self.assertIsNone(payload["controllerState"])
        self.assertEqual(payload["diagnosis"]["state"], "OFFLINE")
        self.assertEqual(payload["diagnosis"]["source"], "jdownloader")

    def test_show_package_failure_preserves_exception_cause(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [{"uuid": 123, "packageUUID": 456}]
        error = RuntimeError("package unavailable")
        device.downloads.query_packages.side_effect = error
        with self.assertRaisesRegex(services.ShowError, "Failed to query parent package") as caught:
            services.show_download(device, 123)
        self.assertIs(caught.exception.__cause__, error)
        device.action.assert_not_called()

    def test_check_all_query_failure_does_not_submit_action(self):
        device = MagicMock()
        device.downloads.query_links.side_effect = RuntimeError("query failed")
        with self.assertRaisesRegex(services.CheckError, "Failed to query download links"):
            services.check_all_downloads(device)
        device.action.assert_not_called()

    def test_check_all_start_failure_is_service_error(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [{"uuid": 123}]
        error = RuntimeError("start failed")
        device.action.side_effect = error
        with self.assertRaisesRegex(services.CheckError, "Failed to start online status check") as caught:
            services.check_all_downloads(device)
        self.assertIs(caught.exception.__cause__, error)

    def test_check_returns_after_unchecked_transitions_to_final_status(self):
        device = MagicMock()
        device.downloads.query_links.side_effect = [
            [self.link("TRUE")], [self.link("UNCHECKED")], [self.link("FALSE")],
        ]
        moments = iter([0.0, 0.1, 0.2])
        pauses = []
        payload = services.check_download(device, 123, clock=lambda: next(moments), sleep=pauses.append)
        self.assertEqual(payload["availableStatus"], {"id": "FALSE"})
        self.assertEqual(pauses, [services.CHECK_POLL_INTERVAL_SECONDS])

    def test_availability_rejects_malformed_state_and_preserves_raw_dict(self):
        from jdsh.diagnostics import available_status

        for link in (None, {}, {"advancedStatus": None}, {"advancedStatus": []},
                     {"advancedStatus": {"AvailableStatus": "TRUE"}}):
            with self.subTest(link=link):
                self.assertIsNone(available_status(link))
        status = {"id": "TRUE", "futureField": None}
        self.assertIs(available_status({"advancedStatus": {"AvailableStatus": status}}), status)


if __name__ == "__main__":
    unittest.main()
