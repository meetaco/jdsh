import subprocess
import unittest
from unittest.mock import patch

from jdsh import clipboard
from jdsh.clipboard import extract_links_from_html, links_from_clipboard_data


class ExtractLinksFromHtmlTests(unittest.TestCase):
    def test_extracts_href_instead_of_display_text(self):
        html = '<a href="https://example.com/target">https://display.invalid/</a>'
        self.assertEqual(extract_links_from_html(html), ["https://example.com/target"])

    def test_extracts_multiple_links(self):
        html = (
            '<p><a href="https://example.com/one">one</a></p>'
            '<a href="https://example.com/two?x=1&amp;y=2">two</a>'
        )
        self.assertEqual(
            extract_links_from_html(html),
            ["https://example.com/one", "https://example.com/two?x=1&y=2"],
        )

    def test_deduplicates_links_while_preserving_order(self):
        html = (
            '<a href="https://example.com/one">first</a>'
            '<a href="https://example.com/two">second</a>'
            '<a href="https://example.com/one">duplicate</a>'
        )
        self.assertEqual(
            extract_links_from_html(html),
            ["https://example.com/one", "https://example.com/two"],
        )


class ClipboardFallbackTests(unittest.TestCase):
    def test_prefers_html_links_over_plain_text(self):
        html = '<a href="https://example.com/from-html">label</a>'
        plain_text = "https://example.com/from-text"
        self.assertEqual(
            links_from_clipboard_data(html, plain_text),
            ["https://example.com/from-html"],
        )

    def test_falls_back_to_plain_text_when_html_has_no_links(self):
        html = "<p>https://display-only.invalid/</p>"
        plain_text = "https://example.com/one\nhttps://example.com/two https://example.com/one"
        self.assertEqual(
            links_from_clipboard_data(html, plain_text),
            ["https://example.com/one", "https://example.com/two"],
        )


class PasteboardReadTests(unittest.TestCase):
    @patch("jdsh.clipboard.shutil.which", return_value="/usr/bin/osascript")
    @patch("jdsh.clipboard.subprocess.run")
    def test_read_pasteboard_type_invokes_osascript(self, mock_run, mock_which):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='<a href="https://example.com">x</a>', stderr=""
        )

        result = clipboard._read_pasteboard_type("public.html")

        self.assertIn("https://example.com", result)
        mock_which.assert_called_once_with("osascript")
        command = mock_run.call_args.args[0]
        self.assertEqual(command[:3], ["/usr/bin/osascript", "-l", "JavaScript"])
        self.assertIn("public.html", command[-1])

    @patch("jdsh.clipboard.shutil.which", return_value="/usr/bin/osascript")
    @patch("jdsh.clipboard.subprocess.run")
    def test_read_pasteboard_type_reports_osascript_error(self, mock_run, _mock_which):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="pasteboard denied\n"
        )

        with self.assertRaisesRegex(clipboard.ClipboardError, "pasteboard denied"):
            clipboard._read_pasteboard_type("public.html")


class ReadClipboardLinksTests(unittest.TestCase):
    @patch("jdsh.clipboard.sys.platform", "linux")
    def test_non_darwin_raises_clear_error(self):
        with self.assertRaisesRegex(
            clipboard.ClipboardError, "--clipboard is only supported on macOS"
        ):
            clipboard.read_clipboard_links()

    @patch("jdsh.clipboard.sys.platform", "darwin")
    @patch("jdsh.clipboard._read_plain_text")
    @patch(
        "jdsh.clipboard._read_pasteboard_type",
        return_value='<a href="https://example.com/html">label</a>',
    )
    def test_read_prefers_html_without_reading_plain_text(self, mock_html, mock_plain):
        self.assertEqual(clipboard.read_clipboard_links(), ["https://example.com/html"])
        mock_html.assert_called_once_with("public.html")
        mock_plain.assert_not_called()

    @patch("jdsh.clipboard.sys.platform", "darwin")
    @patch(
        "jdsh.clipboard._read_plain_text",
        return_value="https://example.com/one https://example.com/one https://example.com/two",
    )
    @patch("jdsh.clipboard._read_pasteboard_type", return_value="<p>no links</p>")
    def test_read_falls_back_to_plain_text(self, mock_html, mock_plain):
        self.assertEqual(
            clipboard.read_clipboard_links(),
            ["https://example.com/one", "https://example.com/two"],
        )
        mock_html.assert_called_once_with("public.html")
        mock_plain.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
