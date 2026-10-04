import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

from jdsh import cli, clipboard, rendering
from jdsh.client import (
    COMPACT_LINK_STATE_QUERY,
    DOWNLOAD_LINK_STATE_QUERY,
    TUI_LINK_STATE_QUERY,
    JDClient,
)


class ParseArgsTests(unittest.TestCase):
    def assert_add_args(self, argv):
        args = cli._parse_args(argv)
        self.assertEqual(args.command, "add")
        self.assertTrue(args.clipboard)
        self.assertEqual(args.urls, ["URL1", "URL2"])

    def test_clipboard_before_urls(self):
        self.assert_add_args(["add", "--clipboard", "URL1", "URL2"])

    def test_clipboard_after_urls(self):
        self.assert_add_args(["add", "URL1", "URL2", "--clipboard"])

    def test_clipboard_between_urls(self):
        self.assert_add_args(["add", "URL1", "--clipboard", "URL2"])

    def test_unknown_argument_is_not_silently_ignored(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as ctx:
            cli._parse_args(["add", "URL1", "--unknown"])
        self.assertEqual(ctx.exception.code, 2)

    def test_add_requires_url_or_clipboard(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as ctx:
            cli._parse_args(["add"])
        self.assertEqual(ctx.exception.code, 2)

    def test_file_option_with_interspersed_urls(self):
        for option in ("--file", "-f"):
            for argv in (
                ["add", option, "links list.txt", "URL1", "URL2"],
                ["add", "URL1", option, "links list.txt", "URL2"],
                ["add", "URL1", "URL2", option, "links list.txt"],
            ):
                with self.subTest(argv=argv):
                    args = cli._parse_args(argv)
                    self.assertEqual(args.file, "links list.txt")
                    self.assertEqual(args.urls, ["URL1", "URL2"])

    def test_file_without_positional_urls(self):
        args = cli._parse_args(["add", "--file", "links.txt"])
        self.assertEqual(args.file, "links.txt")
        self.assertEqual(args.urls, [])

    def test_file_combined_with_clipboard_and_urls(self):
        args = cli._parse_args(["add", "URL1", "--file=links.txt", "--clipboard", "URL2"])
        self.assertEqual(args.file, "links.txt")
        self.assertTrue(args.clipboard)
        self.assertEqual(args.urls, ["URL1", "URL2"])

    def test_file_option_requires_path(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as ctx:
            cli._parse_args(["add", "URL1", "--file"])
        self.assertEqual(ctx.exception.code, 2)

    def test_option_terminator_preserves_literal_arguments(self):
        args = cli._parse_args(["add", "--", "--clipboard", "--file"])
        self.assertFalse(args.clipboard)
        self.assertIsNone(args.file)
        self.assertEqual(args.urls, ["--clipboard", "--file"])


class CmdAddTests(unittest.TestCase):
    def test_file_lines_trim_whitespace_ignore_blanks_and_dedupe(self):
        device = MagicMock()
        args = cli._parse_args(["add", "-f", "links.txt"])
        reader = mock_open(read_data=" https://a.example \r\n\r\n  \nhttps://b.example\nhttps://a.example")
        with patch("builtins.open", reader):
            cli._execute(cli.cmd_add, device, args)
        reader.assert_called_once_with("links.txt", encoding="utf-8-sig")
        device.linkgrabber.add_links.assert_called_once_with([{
            "links": "https://a.example,https://b.example",
            "autostart": False,
            "priority": "DEFAULT",
        }])

    def test_combines_all_sources_in_order(self):
        device = MagicMock()
        args = cli._parse_args(["add", "https://pos.example", "-f", "links.txt", "--clipboard"])
        with patch("builtins.open", mock_open(read_data="https://pos.example\nhttps://file.example\n")), patch.object(
            clipboard, "read_clipboard_links", return_value=["https://file.example", "https://clip.example"]
        ):
            cli._execute(cli.cmd_add, device, args)
        self.assertEqual(device.linkgrabber.add_links.call_args.args[0][0]["links"],
                         "https://pos.example,https://file.example,https://clip.example")

    def test_file_read_errors_prevent_submission(self):
        for error in (FileNotFoundError("missing"), PermissionError("denied"),
                      UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte")):
            with self.subTest(error=error):
                device = MagicMock()
                args = cli._parse_args(["add", "https://pos.example", "--file", "links.txt"])
                with patch("builtins.open", side_effect=error), patch("sys.stderr", new_callable=io.StringIO) as stderr:
                    with self.assertRaises(SystemExit) as ctx:
                        cli._execute(cli.cmd_add, device, args)
                self.assertEqual(ctx.exception.code, 1)
                self.assertIn("cannot read URL file 'links.txt'", stderr.getvalue())
                device.linkgrabber.add_links.assert_not_called()

    def test_empty_file_prevents_empty_submission(self):
        device = MagicMock()
        args = cli._parse_args(["add", "--file", "links.txt"])
        with patch("builtins.open", mock_open(read_data="\n  \n")), patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as ctx:
                cli._execute(cli.cmd_add, device, args)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("no URLs to add", stderr.getvalue())
        device.linkgrabber.add_links.assert_not_called()

    def test_combines_positional_and_clipboard_links_with_ordered_dedupe(self):
        device = MagicMock()
        args = SimpleNamespace(clipboard=True, urls=["https://pos.example", "https://dup.example"])
        with patch.object(
            clipboard,
            "read_clipboard_links",
            return_value=["https://dup.example", "https://clip.example"],
        ):
            cli._execute(cli.cmd_add, device, args)

        payload = device.linkgrabber.add_links.call_args.args[0][0]
        self.assertEqual(
            payload["links"],
            "https://pos.example,https://dup.example,https://clip.example",
        )

    def test_preserves_existing_positional_whitespace_normalization(self):
        device = MagicMock()
        args = SimpleNamespace(clipboard=False, urls=["https://a.example https://b.example"])
        cli._execute(cli.cmd_add, device, args)
        payload = device.linkgrabber.add_links.call_args.args[0][0]
        self.assertEqual(payload["links"], "https://a.example,https://b.example")

    def test_clipboard_error_goes_to_stderr_and_exits_one(self):
        device = MagicMock()
        args = SimpleNamespace(clipboard=True, urls=[])
        with patch.object(
            clipboard,
            "read_clipboard_links",
            side_effect=clipboard.ClipboardError("read failed"),
        ), patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as ctx:
                cli._execute(cli.cmd_add, device, args)

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Error: read failed", stderr.getvalue())
        device.linkgrabber.add_links.assert_not_called()


class RawLinkStateTests(unittest.TestCase):
    def test_state_query_requests_jdownloader_status_fields(self):
        expected_fields = {
            "status",
            "advancedStatus",
            "running",
            "enabled",
            "finished",
            "skipped",
            "extractionStatus",
            "eta",
            "speed",
            "host",
        }
        for field in expected_fields:
            self.assertIs(DOWNLOAD_LINK_STATE_QUERY[field], True)

    def test_compact_query_omits_detail_only_fields(self):
        for field in ("advancedStatus", "extractionStatus", "host", "url", "speed", "eta"):
            self.assertNotIn(field, COMPACT_LINK_STATE_QUERY)

    def test_tui_query_omits_diagnostic_only_fields(self):
        for field in ("advancedStatus", "skipped", "extractionStatus", "host", "url", "uuid"):
            self.assertNotIn(field, TUI_LINK_STATE_QUERY)

    def test_detail_preserves_null_and_advanced_status(self):
        link = {
            "uuid": 123,
            "status": None,
            "running": False,
            "enabled": True,
            "finished": False,
            "skipped": False,
            "extractionStatus": None,
            "eta": -1,
            "speed": 0,
            "host": "example.com",
            "bytesLoaded": 0,
            "bytesTotal": 1000,
            "url": "https://example.com/file",
            "advancedStatus": {
                "ConditionalSkipReason": {
                    "id": "TimeOutCondition",
                    "timeout": 12345,
                }
            },
        }

        text = rendering._raw_detail_text(link).plain
        self.assertIn("status: null", text)
        self.assertIn("running: false", text)
        self.assertIn("enabled: true", text)
        self.assertIn('"id": "TimeOutCondition"', text)
        self.assertIn('"timeout": 12345', text)

    def test_fetch_stats_keeps_api_flags_without_new_state_mapping(self):
        client = JDClient.__new__(JDClient)
        client.device = MagicMock()
        running = {
            "name": "running",
            "running": True,
            "enabled": True,
            "finished": False,
            "status": None,
        }
        enabled_unfinished = {
            "name": "queued",
            "running": False,
            "enabled": True,
            "finished": False,
            "status": None,
        }
        client.device.downloadcontroller.get_current_state.return_value = "IDLE"
        client.device.downloads.query_links.return_value = [running, enabled_unfinished]

        state, running_links, enabled_unfinished_links = client.fetch_stats()

        client.device.downloads.query_links.assert_called_once_with(
            [TUI_LINK_STATE_QUERY.copy()]
        )
        self.assertEqual(state, "IDLE")
        self.assertEqual(running_links, [running])
        self.assertEqual(enabled_unfinished_links, [enabled_unfinished])


if __name__ == "__main__":
    unittest.main()
