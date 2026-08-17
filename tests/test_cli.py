import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jdsh import cli, clipboard


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


if __name__ == "__main__":
    unittest.main()
