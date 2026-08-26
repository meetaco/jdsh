import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.console import Console

from jdsh import cli
from jdsh.client import (
    DOWNLOAD_LINK_STATE_QUERY,
    DOWNLOAD_PACKAGE_STATE_QUERY,
    DOWNLOAD_URL_DISPLAY_TYPES,
)


class ShowCommandTests(unittest.TestCase):
    @staticmethod
    def show_query(link_id):
        query = DOWNLOAD_LINK_STATE_QUERY.copy()
        query["linkUUIDs"] = [link_id]
        return query

    @staticmethod
    def package_query(package_id):
        query = DOWNLOAD_PACKAGE_STATE_QUERY.copy()
        query["packageUUIDs"] = [package_id]
        return query

    @staticmethod
    def build_device():
        device = MagicMock()
        device.downloads.query_links.return_value = [
            {"uuid": 123, "packageUUID": 999, "name": "file.zip"}
        ]
        device.downloads.query_packages.return_value = [
            {
                "uuid": 999,
                "name": "package",
                "saveTo": "/downloads",
                "childCount": 1,
                "hosts": ["example.com"],
            }
        ]
        # DownloadsAPIV2.getDownloadUrls returns Map<String, List<Long>>.
        device.action.return_value = {
            "https://origin.example/file.zip": [123],
            "https://referrer.example/page": [123],
        }
        return device

    def test_parser_accepts_ls_link_id_and_json(self):
        args = cli._parse_args(["show", "123", "--json"])

        self.assertEqual(args.command, "show")
        self.assertEqual(args.id, 123)
        self.assertTrue(args.as_json)

    def test_show_queries_link_parent_package_and_all_download_url_types(self):
        device = self.build_device()
        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=200)

        with patch.object(cli, "Console", return_value=console):
            cli.cmd_show(device, SimpleNamespace(id=123, as_json=False))

        device.downloads.query_links.assert_called_once_with([self.show_query(123)])
        device.downloads.query_packages.assert_called_once_with([self.package_query(999)])
        device.action.assert_called_once_with(
            "/downloadsV2/getDownloadUrls",
            [[123], [], list(DOWNLOAD_URL_DISPLAY_TYPES)],
        )

        rendered = output.getvalue()
        self.assertIn("Link: file.zip", rendered)
        self.assertIn("Package", rendered)
        self.assertIn("saveTo: /downloads", rendered)
        self.assertIn("childCount: 1", rendered)
        self.assertIn("Download URLs", rendered)
        self.assertIn("https://origin.example/file.zip", rendered)

    def test_package_uuid_is_not_accepted_as_show_id(self):
        device = self.build_device()

        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as ctx:
                cli.cmd_show(device, SimpleNamespace(id=999, as_json=False))

        device.downloads.query_links.assert_called_once_with([self.show_query(999)])
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Download link ID not found: 999", stderr.getvalue())
        device.downloads.query_packages.assert_not_called()
        device.action.assert_not_called()

    def test_json_outputs_combined_related_data_with_upstream_url_map_shape(self):
        device = self.build_device()
        expected_urls = device.action.return_value

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            cli.cmd_show(device, SimpleNamespace(id=123, as_json=True))

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["link"]["uuid"], 123)
        self.assertEqual(payload["package"]["uuid"], 999)
        self.assertEqual(payload["downloadUrls"], expected_urls)

    def test_missing_parent_package_uuid_is_reported_as_null_without_package_query(self):
        device = self.build_device()
        device.downloads.query_links.return_value = [{"uuid": 123, "name": "orphan.bin"}]

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            cli.cmd_show(device, SimpleNamespace(id=123, as_json=True))

        self.assertIsNone(json.loads(stdout.getvalue())["package"])
        device.downloads.query_packages.assert_not_called()
        device.action.assert_called_once_with(
            "/downloadsV2/getDownloadUrls",
            [[123], [], list(DOWNLOAD_URL_DISPLAY_TYPES)],
        )

    def test_package_query_failure_is_reported_cleanly(self):
        device = self.build_device()
        device.downloads.query_packages.side_effect = RuntimeError("package unavailable")

        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as ctx:
                cli.cmd_show(device, SimpleNamespace(id=123, as_json=False))

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Failed to query parent package", stderr.getvalue())
        device.action.assert_not_called()

    def test_download_url_query_failure_is_reported_cleanly(self):
        device = self.build_device()
        device.action.side_effect = RuntimeError("URL endpoint unavailable")

        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as ctx:
                cli.cmd_show(device, SimpleNamespace(id=123, as_json=False))

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Failed to query download URLs", stderr.getvalue())

    def test_nested_values_start_on_the_next_line(self):
        text = cli._raw_detail_text(
            {"uuid": 123, "advancedStatus": {"reason": "CAPTCHA"}}
        ).plain

        self.assertIn('advancedStatus:\n{\n  "reason": "CAPTCHA"\n}', text)
        self.assertNotIn("advancedStatus: {", text)

    def test_detail_renders_unanticipated_returned_fields(self):
        text = cli._raw_detail_text(
            {"uuid": 123, "name": "file.zip", "futureField": {"x": 1}}
        ).plain

        self.assertIn("futureField:\n", text)
        self.assertIn('"x": 1', text)

    def test_package_detail_uses_package_field_order(self):
        text = cli._raw_detail_text(
            {"uuid": 999, "name": "package", "saveTo": "/downloads", "childCount": 1},
            cli.PACKAGE_DETAIL_FIELDS,
        ).plain

        self.assertLess(text.index("saveTo:"), text.index("childCount:"))
        self.assertNotIn("packageUUID:", text)

    def test_priority_rendering_is_type_agnostic(self):
        cases = (
            (1, "priority: 1"),
            ("HIGH", "priority: HIGH"),
            ({"name": "HIGH"}, 'priority:\n{\n  "name": "HIGH"\n}'),
        )
        for priority, expected in cases:
            with self.subTest(priority=priority):
                text = cli._raw_detail_text({"uuid": 123, "priority": priority}).plain
                self.assertIn(expected, text)

    def test_show_query_requests_extended_diagnostic_fields(self):
        for field in ("addedDate", "comment", "finishedDate", "priority"):
            self.assertIs(DOWNLOAD_LINK_STATE_QUERY[field], True)

    def test_package_query_requests_upstream_full_fields(self):
        expected = {
            "bytesLoaded",
            "bytesTotal",
            "childCount",
            "comment",
            "enabled",
            "eta",
            "finished",
            "hosts",
            "priority",
            "running",
            "saveTo",
            "speed",
            "status",
        }
        self.assertEqual(set(DOWNLOAD_PACKAGE_STATE_QUERY), expected)
        self.assertNotIn("password", DOWNLOAD_PACKAGE_STATE_QUERY)

    def test_download_url_display_types_are_complete_and_immutable(self):
        self.assertEqual(DOWNLOAD_URL_DISPLAY_TYPES, ("ORIGIN", "REFERRER", "CUSTOM"))
        self.assertIsInstance(DOWNLOAD_URL_DISPLAY_TYPES, tuple)


if __name__ == "__main__":
    unittest.main()
