import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from rich.console import Console

from jdsh import cli
from jdsh.client import CHECK_LINK_STATE_QUERY, start_online_status_check


class CheckCommandTests(unittest.TestCase):
    @staticmethod
    def check_query(link_id):
        query = CHECK_LINK_STATE_QUERY.copy()
        query["linkUUIDs"] = [link_id]
        return query

    @staticmethod
    def link(status_id, label=None):
        status = {"id": status_id}
        if label is not None:
            status["label"] = label
        return {
            "uuid": 123,
            "name": "file.zip",
            "advancedStatus": {"AvailableStatus": status},
        }

    def test_parser_accepts_check_id_and_json(self):
        args = cli._parse_args(["check", "123", "--json"])
        self.assertEqual(args.command, "check")
        self.assertEqual(args.id, 123)
        self.assertTrue(args.as_json)

    def test_start_online_status_check_uses_downloadsv2_endpoint(self):
        device = MagicMock()
        start_online_status_check(device, [123])
        device.action.assert_called_once_with(
            "/downloadsV2/startOnlineStatusCheck",
            [[123], []],
        )

    def test_check_waits_for_unchecked_then_returns_offline(self):
        device = MagicMock()
        device.downloads.query_links.side_effect = [
            [self.link("TRUE", "Online")],
            [self.link("UNCHECKED")],
            [self.link("FALSE", "Offline")],
        ]
        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=120)

        with patch.object(cli, "Console", return_value=console), \
             patch.object(cli.time, "monotonic", side_effect=[0.0, 0.1, 0.2, 0.3]), \
             patch.object(cli.time, "sleep"):
            cli.cmd_check(device, SimpleNamespace(id=123, as_json=False))

        self.assertEqual(device.downloads.query_links.call_args_list, [
            call([self.check_query(123)]),
            call([self.check_query(123)]),
            call([self.check_query(123)]),
        ])
        device.action.assert_called_once_with(
            "/downloadsV2/startOnlineStatusCheck", [[123], []]
        )
        rendered = output.getvalue()
        self.assertIn("file.zip", rendered)
        self.assertIn("FALSE (Offline)", rendered)

    def test_fast_same_result_is_accepted_after_grace_period(self):
        device = MagicMock()
        device.downloads.query_links.side_effect = [
            [self.link("TRUE", "Online")],
            [self.link("TRUE", "Online")],
            [self.link("TRUE", "Online")],
            [self.link("TRUE", "Online")],
        ]
        times = [0.0, 0.1, 0.2, 1.1]

        with patch.object(cli.time, "monotonic", side_effect=times), \
             patch.object(cli.time, "sleep"), \
             patch("sys.stdout", new_callable=io.StringIO) as stdout:
            cli.cmd_check(device, SimpleNamespace(id=123, as_json=True))

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["availableStatus"]["id"], "TRUE")

    def test_missing_link_is_reported_cleanly_without_starting_check(self):
        device = MagicMock()
        device.downloads.query_links.return_value = []

        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as ctx:
                cli.cmd_check(device, SimpleNamespace(id=999, as_json=False))

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Download link ID not found: 999", stderr.getvalue())
        device.action.assert_not_called()

    def test_start_failure_is_reported_cleanly(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [self.link("TRUE", "Online")]
        device.action.side_effect = RuntimeError("endpoint unavailable")

        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as ctx:
                cli.cmd_check(device, SimpleNamespace(id=123, as_json=False))

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Failed to start online status check", stderr.getvalue())

    def test_check_times_out_if_status_stays_unchecked(self):
        device = MagicMock()
        device.downloads.query_links.side_effect = [
            [self.link("TRUE", "Online")],
            [self.link("UNCHECKED")],
            [self.link("UNCHECKED")],
            [self.link("UNCHECKED")],
        ]

        with patch.object(cli, "CHECK_TIMEOUT_SECONDS", 0.5), \
             patch.object(cli.time, "monotonic", side_effect=[0.0, 0.1, 0.2, 0.6]), \
             patch.object(cli.time, "sleep"), \
             patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as ctx:
                cli.cmd_check(device, SimpleNamespace(id=123, as_json=False))

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("timed out after 0.5s", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
