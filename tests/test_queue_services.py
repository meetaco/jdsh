"""Operation boundaries preserve raw responses and submit queue changes once."""

import contextlib
import io
import unittest
from copy import deepcopy
from unittest.mock import MagicMock, call, patch

from rich.console import Console

from jdsh import cli, config, services
from jdsh.client import (
    DOWNLOAD_LINK_STATE_QUERY, GRABBER_LINK_STATE_QUERY,
    LIST_LINK_STATE_QUERY, STATUS_LINK_STATE_QUERY,
)


class QueueServiceTests(unittest.TestCase):
    def test_status_reads_controller_before_links_and_returns_raw_response(self):
        device = MagicMock()
        links = [{"name": "done", "finished": True, "running": True, "future": None}]
        device.downloadcontroller.get_current_state.return_value = "RUNNING"
        device.downloads.query_links.return_value = links
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            state, result = services.download_status(device)
        self.assertEqual(state, "RUNNING")
        self.assertIs(result, links)
        self.assertEqual(device.mock_calls, [
            call.downloadcontroller.get_current_state(),
            call.downloads.query_links([STATUS_LINK_STATE_QUERY]),
        ])
        self.assertTrue(STATUS_LINK_STATE_QUERY["finished"])
        self.assertEqual((stdout.getvalue(), stderr.getvalue()), ("", ""))

    def test_query_mutation_does_not_leak_to_later_requests(self):
        for operation, kwargs, fields in (
            (services.download_status, {}, STATUS_LINK_STATE_QUERY),
            (services.list_downloads, {}, LIST_LINK_STATE_QUERY),
            (services.list_downloads, {"detail": True}, DOWNLOAD_LINK_STATE_QUERY),
        ):
            with self.subTest(operation=operation.__name__, kwargs=kwargs):
                device = MagicMock()
                expected = dict(fields)
                requests = []

                def query(payload):
                    requests.append(deepcopy(payload))
                    payload[0]["linkUUIDs"] = [999]
                    return []

                device.downloads.query_links.side_effect = query
                operation(device, **kwargs)
                operation(device, **kwargs)
                self.assertEqual(fields, expected)
                self.assertEqual(requests, [[expected], [expected]])

    def test_new_query_definitions_cannot_be_mutated(self):
        for fields in (STATUS_LINK_STATE_QUERY, GRABBER_LINK_STATE_QUERY):
            with self.subTest(fields=fields):
                with self.assertRaises(TypeError):
                    fields["name"] = False
                self.assertIs(fields["name"], True)

    def test_grabber_query_mutation_does_not_leak_to_later_requests(self):
        device = MagicMock()
        requests = []

        def query(payload):
            requests.append(deepcopy(payload))
            payload[0]["url"] = False
            return []

        device.linkgrabber.query_links.side_effect = query
        services.list_grabber_links(device)
        services.list_grabber_links(device)
        self.assertEqual(requests, [[dict(GRABBER_LINK_STATE_QUERY)]] * 2)

    def test_grabber_preserves_raw_fields(self):
        device = MagicMock()
        links = [{"uuid": 123, "name": "file.zip", "url": None, "future": False}]
        device.linkgrabber.query_links.return_value = links
        self.assertIs(services.list_grabber_links(device), links)
        device.linkgrabber.query_links.assert_called_once_with([
            {"name": True, "uuid": True, "url": True},
        ])

    def test_add_preserves_duplicates_order_and_does_not_autostart(self):
        device = MagicMock()
        links = ["https://a.example", "https://b.example", "https://a.example"]
        services.add_to_grabber(device, links)
        self.assertEqual(device.mock_calls, [call.linkgrabber.add_links([{
            "links": "https://a.example,https://b.example,https://a.example",
            "autostart": False, "priority": "DEFAULT",
        }])])
        self.assertEqual(links, ["https://a.example", "https://b.example", "https://a.example"])

    def test_confirm_moves_all_packages_once_in_api_order(self):
        device = MagicMock()
        device.linkgrabber.query_packages.return_value = [{"uuid": 8}, {"uuid": 3}]
        self.assertEqual(services.confirm_grabber(device), 2)
        self.assertEqual(device.mock_calls, [
            call.linkgrabber.query_packages([{"uuid": True}]),
            call.linkgrabber.move_to_downloadlist([], [8, 3]),
        ])

    def test_empty_grabber_does_not_mutate_queue(self):
        device = MagicMock()
        device.linkgrabber.query_packages.return_value = []
        self.assertEqual(services.confirm_grabber(device), 0)
        self.assertEqual(device.mock_calls, [call.linkgrabber.query_packages([{"uuid": True}])])

    def test_remove_and_clear_keep_distinct_selection_scopes(self):
        device = MagicMock()
        services.remove_downloads(device, ["8", "3"])
        services.clear_finished_downloads(device)
        self.assertEqual(device.mock_calls, [
            call.downloads.remove_links([8, 3], []),
            call.downloads.cleanup("DELETE_FINISHED", "REMOVE_LINKS_ONLY", "ALL", [], []),
        ])

    def test_controller_and_revision_calls_keep_original_endpoints(self):
        device = MagicMock()
        device.action.return_value = 12345
        services.start_downloads(device)
        services.stop_downloads(device)
        self.assertEqual(services.core_revision(device), 12345)
        self.assertEqual(device.mock_calls, [
            call.downloadcontroller.start_downloads(),
            call.downloadcontroller.stop_downloads(),
            call.action("/jd/getCoreRevision", []),
        ])

    def test_controller_query_failure_does_not_fetch_links(self):
        device = MagicMock()
        error = RuntimeError("controller denied")
        device.downloadcontroller.get_current_state.side_effect = error
        with self.assertRaises(RuntimeError) as caught:
            services.download_status(device)
        self.assertIs(caught.exception, error)
        device.downloads.query_links.assert_not_called()


class QueueCommandFailureTests(unittest.TestCase):
    def test_mutation_failures_never_print_success_or_retry(self):
        cases = (
            (["add", "https://example.org"], "linkgrabber", "add_links"),
            (["confirm"], "linkgrabber", "query_packages"),
            (["confirm"], "linkgrabber", "move_to_downloadlist"),
            (["remove", "123"], "downloads", "remove_links"),
            (["start"], "downloadcontroller", "start_downloads"),
            (["stop"], "downloadcontroller", "stop_downloads"),
            (["clear"], "downloads", "cleanup"),
        )
        for argv, section, method in cases:
            with self.subTest(argv=argv, method=method):
                device = MagicMock()
                device.linkgrabber.query_packages.return_value = [{"uuid": 123}]
                failing_call = getattr(getattr(device, section), method)
                error = RuntimeError("operation denied")
                failing_call.side_effect = error
                client = MagicMock()
                client.connect.return_value = device
                output, stdout, stderr = io.StringIO(), io.StringIO(), io.StringIO()
                console = Console(file=output, force_terminal=False)
                with patch.object(cli, "JDClient", return_value=client), \
                     patch.object(cli.config, "load_settings", return_value=config.Settings()), \
                     contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as caught:
                        cli.main(argv, console=console)
                self.assertEqual(caught.exception.code, 1)
                self.assertIs(caught.exception.__cause__, error)
                self.assertEqual(output.getvalue(), "")
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(stderr.getvalue(), "Error: operation denied\n")
                failing_call.assert_called_once()
                if method == "query_packages":
                    device.linkgrabber.move_to_downloadlist.assert_not_called()

    def test_simple_command_needs_only_selected_controller_method(self):
        from types import SimpleNamespace
        device = SimpleNamespace(downloadcontroller=SimpleNamespace(start_downloads=MagicMock()))
        output = io.StringIO()
        cli.cmd_simple(device, SimpleNamespace(command="start"),
                       console=Console(file=output, force_terminal=False))
        device.downloadcontroller.start_downloads.assert_called_once_with()
        self.assertIn("Command executed: start", output.getvalue())

    def test_unavailable_core_revision_keeps_version_fallback(self):
        device = MagicMock()
        device.action.side_effect = RuntimeError("unavailable")
        output, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cli.cmd_version(device, None, console=Console(file=output, force_terminal=False))
        self.assertIn(f"JDSH v{config.VERSION}", output.getvalue())
        self.assertIn("JD Core: Unknown", output.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        device.action.assert_called_once_with("/jd/getCoreRevision", [])
