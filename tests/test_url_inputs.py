"""Verify input order and failures independently of CLI, API and macOS tools."""

import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch

from jdsh import clipboard, url_inputs
from jdsh.errors import JDShError


class URLInputTests(unittest.TestCase):
    def test_positional_only_keeps_duplicates_and_splits_whitespace_without_io(self):
        read_file, read_clipboard = MagicMock(), MagicMock()
        urls = ["https://a.example\nhttps://b.example", "https://a.example"]
        self.assertEqual(url_inputs.collect_links(
            urls, read_file=read_file, read_clipboard=read_clipboard,
        ), ["https://a.example", "https://b.example", "https://a.example"])
        self.assertEqual(urls, ["https://a.example\nhttps://b.example", "https://a.example"])
        read_file.assert_not_called()
        read_clipboard.assert_not_called()

    def test_collects_sources_in_order_and_dedupes_across_them(self):
        events = []

        def read_file(path):
            events.append(("file", path))
            return ["https://a.example", "https://b.example"]

        def read_clipboard():
            events.append(("clipboard",))
            return ["https://b.example", "https://c.example"]

        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = url_inputs.collect_links(
                ["https://a.example"], file_path="links.txt", use_clipboard=True,
                read_file=read_file, read_clipboard=read_clipboard,
            )
        self.assertEqual(result, ["https://a.example", "https://b.example", "https://c.example"])
        self.assertEqual(events, [("file", "links.txt"), ("clipboard",)])
        self.assertEqual((stdout.getvalue(), stderr.getvalue()), ("", ""))

    def test_empty_file_still_enables_deduplication_of_positionals(self):
        self.assertEqual(url_inputs.collect_links(
            ["https://a.example", "https://a.example"], file_path="empty.txt", read_file=lambda _: [],
        ), ["https://a.example"])

    def test_file_decodes_bom_trims_lines_and_keeps_internal_whitespace(self):
        data = b"\xef\xbb\xbf https://a.example \r\n \nhttps://b.example https://c.example\r\n"
        streams = []

        def open_file(path, **kwargs):
            stream = io.TextIOWrapper(io.BytesIO(data), encoding=kwargs["encoding"])
            streams.append(stream)
            return stream

        with patch("builtins.open", side_effect=open_file) as reader:
            result = url_inputs.collect_links([], file_path="links.txt")
        reader.assert_called_once_with("links.txt", encoding="utf-8-sig")
        self.assertEqual(result, ["https://a.example", "https://b.example https://c.example"])
        self.assertTrue(streams[0].closed)

    def test_file_read_failure_aborts_before_reading_clipboard(self):
        for error in (FileNotFoundError("missing"), PermissionError("denied"),
                      UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")):
            with self.subTest(error=type(error).__name__):
                read_file = MagicMock(side_effect=error)
                read_clipboard = MagicMock()
                with self.assertRaisesRegex(JDShError, "cannot read URL file 'links.txt'") as caught:
                    url_inputs.collect_links(["https://valid.example"], file_path="links.txt",
                                             use_clipboard=True, read_file=read_file,
                                             read_clipboard=read_clipboard)
                self.assertIs(caught.exception.__cause__, error)
                read_clipboard.assert_not_called()

    def test_lazy_file_failure_is_not_returned_as_partial_success(self):
        error = OSError("read interrupted")

        def read_file(_):
            yield "https://first.example"
            raise error

        with self.assertRaisesRegex(JDShError, "read interrupted") as caught:
            url_inputs.collect_links([], file_path="links.txt", read_file=read_file)
        self.assertIs(caught.exception.__cause__, error)

    def test_clipboard_failure_preserves_original_exception_and_aborts_collection(self):
        error = clipboard.ClipboardError("pasteboard denied")
        with self.assertRaises(clipboard.ClipboardError) as caught:
            url_inputs.collect_links(["https://a.example"], use_clipboard=True,
                                     read_clipboard=MagicMock(side_effect=error))
        self.assertIs(caught.exception, error)

    def test_html_href_priority_remains_when_collecting_all_sources(self):
        html = '<a href="https://target.example?x=1&amp;y=2">https://display.invalid</a>'
        self.assertEqual(url_inputs.collect_links(
            ["https://first.example"], use_clipboard=True,
            read_clipboard=lambda: clipboard.links_from_clipboard_data(html, "https://plain.invalid"),
        ), ["https://first.example", "https://target.example?x=1&y=2"])

    def test_empty_collection_is_an_error_for_every_source_combination(self):
        for file_path, use_clipboard in ((None, False), ("empty.txt", False),
                                         (None, True), ("empty.txt", True)):
            with self.subTest(file_path=file_path, use_clipboard=use_clipboard):
                with self.assertRaisesRegex(JDShError, "no URLs to add"):
                    url_inputs.collect_links([], file_path=file_path, use_clipboard=use_clipboard,
                                             read_file=lambda _: [], read_clipboard=lambda: [])
