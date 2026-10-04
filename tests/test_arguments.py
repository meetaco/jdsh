import io
import unittest
from unittest.mock import patch

from jdsh import arguments


class ParseArgsTests(unittest.TestCase):
    def test_normalization_does_not_mutate_caller_arguments(self):
        argv = ["add", "URL1", "--clipboard", "URL2"]
        original = list(argv)
        arguments.parse_args(argv)
        self.assertEqual(argv, original)

    def assert_add_args(self, argv):
        args = arguments.parse_args(argv)
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
            arguments.parse_args(["add", "URL1", "--unknown"])
        self.assertEqual(ctx.exception.code, 2)

    def test_add_requires_url_or_clipboard(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as ctx:
            arguments.parse_args(["add"])
        self.assertEqual(ctx.exception.code, 2)

    def test_file_option_with_interspersed_urls(self):
        for option in ("--file", "-f"):
            for argv in (
                ["add", option, "links list.txt", "URL1", "URL2"],
                ["add", "URL1", option, "links list.txt", "URL2"],
                ["add", "URL1", "URL2", option, "links list.txt"],
            ):
                with self.subTest(argv=argv):
                    args = arguments.parse_args(argv)
                    self.assertEqual(args.file, "links list.txt")
                    self.assertEqual(args.urls, ["URL1", "URL2"])

    def test_file_without_positional_urls(self):
        args = arguments.parse_args(["add", "--file", "links.txt"])
        self.assertEqual(args.file, "links.txt")
        self.assertEqual(args.urls, [])

    def test_file_combined_with_clipboard_and_urls(self):
        args = arguments.parse_args(["add", "URL1", "--file=links.txt", "--clipboard", "URL2"])
        self.assertEqual(args.file, "links.txt")
        self.assertTrue(args.clipboard)
        self.assertEqual(args.urls, ["URL1", "URL2"])

    def test_file_option_requires_path(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as ctx:
            arguments.parse_args(["add", "URL1", "--file"])
        self.assertEqual(ctx.exception.code, 2)

    def test_option_terminator_preserves_literal_arguments(self):
        args = arguments.parse_args(["add", "--", "--clipboard", "--file"])
        self.assertFalse(args.clipboard)
        self.assertIsNone(args.file)
        self.assertEqual(args.urls, ["--clipboard", "--file"])

