import unittest

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


if __name__ == "__main__":
    unittest.main()
