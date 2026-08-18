import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.console import Console

from jdsh import cli
from jdsh.client import DOWNLOAD_LINK_STATE_QUERY


class CompactRawLinkStateTests(unittest.TestCase):
    def test_compact_list_exposes_raw_status_flags(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [
            {
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
        ]
        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=200)

        with patch.object(cli, "Console", return_value=console):
            cli.cmd_list(device, SimpleNamespace(detail=False))

        device.downloads.query_links.assert_called_once_with(
            [DOWNLOAD_LINK_STATE_QUERY.copy()]
        )
        rendered = output.getvalue()
        for header in ("Status", "Running", "Enabled", "Skipped", "Finished"):
            self.assertIn(header, rendered)
        self.assertIn("null", rendered)
        self.assertIn("false", rendered)
        self.assertIn("true", rendered)
        self.assertIn("file.zip", rendered)


if __name__ == "__main__":
    unittest.main()
