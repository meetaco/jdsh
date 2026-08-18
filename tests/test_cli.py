import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jdsh import cli, clipboard
from jdsh.client import DOWNLOAD_LINK_STATE_QUERY, JDClient


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


class CmdAddTests(unittest.TestCase):
    def test_combines_positional_and_clipboard_links_with_ordered_dedupe(self):
        device = MagicMock()
        args = SimpleNamespace(clipboard=True, urls=["https://pos.example", "https://dup.example"])
        with patch.object(
            cli.clipboard,
            "read_clipboard_links",
            return_value=["https://dup.example", "https://clip.example"],
        ):
            cli.cmd_add(device, args)

        payload = device.linkgrabber.add_links.call_args.args[0][0]
        self.assertEqual(
            payload["links"],
            "https://pos.example,https://dup.example,https://clip.example",
        )

    def test_preserves_existing_positional_whitespace_normalization(self):
        device = MagicMock()
        args = SimpleNamespace(clipboard=False, urls=["https://a.example https://b.example"])
        cli.cmd_add(device, args)
        payload = device.linkgrabber.add_links.call_args.args[0][0]
        self.assertEqual(payload["links"], "https://a.example,https://b.example")

    def test_clipboard_error_goes_to_stderr_and_exits_one(self):
        device = MagicMock()
        args = SimpleNamespace(clipboard=True, urls=[])
        with patch.object(
            cli.clipboard,
            "read_clipboard_links",
            side_effect=clipboard.ClipboardError("read failed"),
        ), patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as ctx:
                cli.cmd_add(device, args)

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

        text = cli._raw_detail_text(link).plain
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

        query = client.device.downloads.query_links.call_args.args[0][0]
        self.assertTrue(query["advancedStatus"])
        self.assertTrue(query["skipped"])
        self.assertEqual(state, "IDLE")
        self.assertEqual(running_links, [running])
        self.assertEqual(enabled_unfinished_links, [enabled_unfinished])


if __name__ == "__main__":
    unittest.main()
