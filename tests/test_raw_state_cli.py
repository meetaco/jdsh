import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.console import Console

from jdsh import cli
from jdsh.client import DOWNLOAD_LINK_STATE_QUERY, LIST_LINK_STATE_QUERY


class CompactDiagnosticListTests(unittest.TestCase):
    def render_compact(self, **overrides):
        link = {
            "uuid": 123,
            "name": "file.zip",
            "bytesLoaded": 0,
            "bytesTotal": 1000,
            "status": None,
            "running": False,
            "enabled": True,
            "skipped": False,
            "finished": False,
            "host": "example.com",
            "advancedStatus": {
                "AvailableStatus": {"id": "TRUE", "label": "Online"},
            },
        }
        link.update(overrides)

        device = MagicMock()
        device.downloads.query_links.return_value = [link]
        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=240)

        with patch.object(cli, "Console", return_value=console):
            cli.cmd_list(device, SimpleNamespace(detail=False))

        device.downloads.query_links.assert_called_once_with(
            [LIST_LINK_STATE_QUERY.copy()]
        )
        return output.getvalue()

    def test_compact_list_surfaces_operational_state(self):
        rendered = self.render_compact()

        for header in ("State", "Availability", "Reason", "Host"):
            self.assertIn(header, rendered)
        self.assertIn("WAITING", rendered)
        self.assertIn("TRUE (Online)", rendered)
        self.assertIn("No link-level reason is exposed", rendered)
        self.assertIn("example.com", rendered)
        self.assertIn("file.zip", rendered)

    def test_compact_list_surfaces_explicit_skip_reason(self):
        rendered = self.render_compact(
            skipped=True,
            advancedStatus={
                "AvailableStatus": {"id": "TRUE", "label": "Online"},
                "SkipReason": {"id": "CAPTCHA", "label": "Captcha required"},
            },
        )

        self.assertIn("SKIPPED", rendered)
        self.assertIn("Captcha required", rendered)

    def test_compact_list_preserves_zero_total_bytes(self):
        rendered = self.render_compact(bytesLoaded=0, bytesTotal=0)
        self.assertIn("0 B/0 B", rendered)

    def test_compact_list_preserves_null_byte_values(self):
        rendered = self.render_compact(bytesLoaded=None, bytesTotal=None)
        self.assertIn("null/null", rendered)

    def test_detail_list_uses_full_diagnostic_query(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [
            {
                "uuid": 123,
                "name": "file.zip",
                "bytesLoaded": 0,
                "bytesTotal": 0,
                "status": None,
                "running": False,
                "enabled": True,
                "skipped": False,
                "finished": False,
                "extractionStatus": None,
                "eta": -1,
                "speed": 0,
                "host": "example.com",
                "url": "https://example.com/file.zip",
                "advancedStatus": None,
            }
        ]
        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=200)

        with patch.object(cli, "Console", return_value=console):
            cli.cmd_list(device, SimpleNamespace(detail=True))

        device.downloads.query_links.assert_called_once_with(
            [DOWNLOAD_LINK_STATE_QUERY.copy()]
        )
        self.assertIn("advancedStatus", output.getvalue())


if __name__ == "__main__":
    unittest.main()
