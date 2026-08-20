import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.console import Console

from jdsh import cli
from jdsh.client import DOWNLOAD_LINK_STATE_QUERY


class ShowCommandTests(unittest.TestCase):
    @staticmethod
    def show_query(link_id):
        query = DOWNLOAD_LINK_STATE_QUERY.copy()
        query["linkUUIDs"] = [link_id]
        return query

    def test_parser_accepts_ls_link_id_and_json(self):
        args = cli._parse_args(["show", "123", "--json"])

        self.assertEqual(args.command, "show")
        self.assertEqual(args.id, 123)
        self.assertTrue(args.as_json)

    def test_show_uses_download_link_uuid_from_ls(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [
            {"uuid": 123, "packageUUID": 999, "name": "first.zip"},
            {"uuid": 456, "packageUUID": 888, "name": "second.zip"},
        ]
        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=200)

        with patch.object(cli, "Console", return_value=console):
            cli.cmd_show(device, SimpleNamespace(id=456, as_json=False))

        device.downloads.query_links.assert_called_once_with(
            [self.show_query(456)]
        )
        rendered = output.getvalue()
        self.assertIn("uuid: 456", rendered)
        self.assertIn("packageUUID: 888", rendered)
        self.assertNotIn("uuid: 123", rendered)

    def test_package_uuid_is_not_accepted_as_show_id(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [
            {"uuid": 123, "packageUUID": 999, "name": "file.zip"}
        ]

        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as ctx:
                cli.cmd_show(device, SimpleNamespace(id=999, as_json=False))

        device.downloads.query_links.assert_called_once_with(
            [self.show_query(999)]
        )
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Download link ID not found: 999", stderr.getvalue())

    def test_json_outputs_selected_raw_link(self):
        link = {
            "uuid": 123,
            "name": "file.zip",
            "advancedStatus": {"reason": "CAPTCHA"},
        }
        device = MagicMock()
        device.downloads.query_links.return_value = [link]

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            cli.cmd_show(device, SimpleNamespace(id=123, as_json=True))

        device.downloads.query_links.assert_called_once_with(
            [self.show_query(123)]
        )
        self.assertEqual(json.loads(stdout.getvalue()), link)

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


if __name__ == "__main__":
    unittest.main()
