import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.console import Console

from jdsh import cli
from jdsh.client import DOWNLOAD_LINK_STATE_QUERY


class ShowCommandTests(unittest.TestCase):
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
            [DOWNLOAD_LINK_STATE_QUERY.copy()]
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

        self.assertEqual(json.loads(stdout.getvalue()), link)

    def test_detail_includes_unanticipated_api_fields(self):
        text = cli._raw_detail_text(
            {"uuid": 123, "name": "file.zip", "futureField": {"x": 1}}
        ).plain

        self.assertIn("futureField:", text)
        self.assertIn('"x": 1', text)

    def test_show_query_requests_extended_diagnostic_fields(self):
        for field in ("addedDate", "comment", "finishedDate", "priority"):
            self.assertIs(DOWNLOAD_LINK_STATE_QUERY[field], True)


if __name__ == "__main__":
    unittest.main()
