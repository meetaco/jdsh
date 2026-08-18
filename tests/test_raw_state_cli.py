import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.console import Console

from jdsh import cli
from jdsh.client import DOWNLOAD_LINK_STATE_QUERY


class CompactRawLinkStateTests(unittest.TestCase):
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
        }
        link.update(overrides)

        device = MagicMock()
        device.downloads.query_links.return_value = [link]
        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=200)

        with patch.object(cli, "Console", return_value=console):
            cli.cmd_list(device, SimpleNamespace(detail=False))

        device.downloads.query_links.assert_called_once_with(
            [DOWNLOAD_LINK_STATE_QUERY.copy()]
        )
        return output.getvalue()

    def test_compact_list_exposes_raw_status_flags(self):
        rendered = self.render_compact()

        for header in ("Status", "Running", "Enabled", "Skipped", "Finished"):
            self.assertIn(header, rendered)
        self.assertIn("null", rendered)
        self.assertIn("false", rendered)
        self.assertIn("true", rendered)
        self.assertIn("file.zip", rendered)

    def test_compact_list_preserves_zero_total_bytes(self):
        rendered = self.render_compact(bytesLoaded=0, bytesTotal=0)
        self.assertIn("0 B/0 B", rendered)

    def test_compact_list_preserves_null_byte_values(self):
        rendered = self.render_compact(bytesLoaded=None, bytesTotal=None)
        self.assertIn("null/null", rendered)


if __name__ == "__main__":
    unittest.main()
