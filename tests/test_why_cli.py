import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.console import Console

from jdsh import cli
from jdsh.client import DOWNLOAD_LINK_STATE_QUERY
from jdsh.diagnostics import diagnose_link


class DiagnoseLinkTests(unittest.TestCase):
    def base_link(self, **overrides):
        link = {
            "uuid": 123,
            "name": "file.zip",
            "status": None,
            "running": False,
            "enabled": True,
            "skipped": False,
            "finished": False,
            "advancedStatus": {
                "AvailableStatus": {"id": "TRUE", "label": "Online"},
            },
        }
        link.update(overrides)
        return link

    def test_conditional_skip_is_explicit_jdownloader_reason(self):
        diagnosis = diagnose_link(
            self.base_link(
                advancedStatus={
                    "AvailableStatus": {"id": "TRUE", "label": "Online"},
                    "ConditionalSkipReason": {
                        "id": "TimeOutCondition",
                        "label": "Wait before retry",
                    },
                }
            )
        )

        self.assertEqual(diagnosis["state"], "WAITING")
        self.assertEqual(diagnosis["reason"], "Wait before retry")
        self.assertEqual(diagnosis["source"], "jdownloader")

    def test_controller_stopped_is_marked_as_inference(self):
        diagnosis = diagnose_link(self.base_link(), controller_state="STOPPED")

        self.assertEqual(diagnosis["state"], "WAITING")
        self.assertEqual(diagnosis["source"], "inferred")
        self.assertIn("controller is STOPPED", diagnosis["reason"])

    def test_idle_online_link_does_not_invent_slot_reason(self):
        diagnosis = diagnose_link(self.base_link(), controller_state="RUNNING")

        self.assertEqual(diagnosis["state"], "WAITING")
        self.assertEqual(diagnosis["source"], "unknown")
        self.assertIn("No link-level reason is exposed", diagnosis["reason"])
        self.assertNotIn("slot", diagnosis["reason"].lower())

    def test_offline_availability_is_explicit(self):
        diagnosis = diagnose_link(
            self.base_link(
                advancedStatus={
                    "AvailableStatus": {"id": "FALSE", "label": "Offline"},
                }
            )
        )

        self.assertEqual(diagnosis["state"], "OFFLINE")
        self.assertEqual(diagnosis["source"], "jdownloader")


class WhyCommandTests(unittest.TestCase):
    @staticmethod
    def query(link_id):
        query = DOWNLOAD_LINK_STATE_QUERY.copy()
        query["linkUUIDs"] = [link_id]
        return query

    def build_device(self):
        device = MagicMock()
        device.downloads.query_links.return_value = [
            {
                "uuid": 123,
                "name": "file.zip",
                "status": None,
                "running": False,
                "enabled": True,
                "skipped": False,
                "finished": False,
                "advancedStatus": {
                    "AvailableStatus": {"id": "TRUE", "label": "Online"},
                },
                "extractionStatus": None,
            }
        ]
        device.downloadcontroller.get_current_state.return_value = "RUNNING"
        return device

    def test_parser_accepts_why_json(self):
        args = cli._parse_args(["why", "123", "--json"])
        self.assertEqual(args.command, "why")
        self.assertEqual(args.id, 123)
        self.assertTrue(args.as_json)

    def test_why_queries_selected_link_and_controller(self):
        device = self.build_device()
        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=200)

        with patch.object(cli, "Console", return_value=console):
            cli.cmd_why(device, SimpleNamespace(id=123, as_json=False))

        device.downloads.query_links.assert_called_once_with([self.query(123)])
        device.downloadcontroller.get_current_state.assert_called_once_with()
        rendered = output.getvalue()
        self.assertIn("WAITING", rendered)
        self.assertIn("TRUE (Online)", rendered)
        self.assertIn("unknown", rendered)
        self.assertIn("raw evidence remains available", rendered)

    def test_json_preserves_provenance_and_raw_status(self):
        device = self.build_device()

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            cli.cmd_why(device, SimpleNamespace(id=123, as_json=True))

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["controllerState"], "RUNNING")
        self.assertEqual(payload["diagnosis"]["source"], "unknown")
        self.assertIsNone(payload["status"])
        self.assertEqual(payload["advancedStatus"]["AvailableStatus"]["id"], "TRUE")

    def test_controller_failure_does_not_hide_link_diagnosis(self):
        device = self.build_device()
        device.downloadcontroller.get_current_state.side_effect = RuntimeError("unavailable")

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            cli.cmd_why(device, SimpleNamespace(id=123, as_json=True))

        payload = json.loads(stdout.getvalue())
        self.assertIsNone(payload["controllerState"])
        self.assertEqual(payload["diagnosis"]["state"], "WAITING")

    def test_missing_link_is_reported_cleanly(self):
        device = self.build_device()
        device.downloads.query_links.return_value = []

        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as ctx:
                cli.cmd_why(device, SimpleNamespace(id=999, as_json=False))

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Download link ID not found: 999", stderr.getvalue())
        device.downloadcontroller.get_current_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
