"""Security regression: arbitrary process arguments must never be published."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools.process_evidence import export, public_snapshot


class ProcessEvidence(unittest.TestCase):
    def test_actual_guard_still_rejects_work_without_writing_arguments(self):
        from tools.full_strength import HostGuard

        owner = 900000
        rows = [
            {
                "pid": 12,
                "ppid": 1,
                "state": "S",
                "cpu": 5,
                "command": "make build --token=SYNTHETIC",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("tools.full_strength.process_rows", return_value=rows),
                patch("tools.full_strength.os.getpid", return_value=owner),
            ):
                with self.assertRaisesRegex(ValueError, "decisive timed games"):
                    HostGuard(Path(directory), Mock(), require_idle=True).check()
            text = (Path(directory) / "HOST_SAMPLES.jsonl").read_text()
            self.assertNotIn("SYNTHETIC", text)
            self.assertNotIn("command", text)
            self.assertEqual(json.loads(text)["offenders"][0]["pid"], 12)

    def test_unknown_process_fields_and_all_arguments_are_omitted(self):
        row = {
            "pid": 11,
            "ppid": 1,
            "state": "Ss+",
            "cpu": 12.5,
            "command": "app --token=SYNTHETIC --csrf_token SYNTHETIC",
            "future_secret_field": "SYNTHETIC",
        }
        snapshot = {
            "unix": 123,
            "load": [1, 2, 3],
            "offenders": [row],
            "top_processes": [row],
            "future_secret_field": "SYNTHETIC",
        }
        result = public_snapshot(snapshot)
        self.assertNotIn("SYNTHETIC", json.dumps(result))
        self.assertEqual(
            result["offenders"], [{"pid": 11, "ppid": 1, "state": "Ss+", "cpu": 12.5}]
        )
        self.assertEqual(result["unix"], snapshot["unix"])
        self.assertEqual(result["load"], snapshot["load"])
        self.assertIn("command", row)

    def test_export_preserves_input_and_refuses_existing_or_linked_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "raw", root / "public"
            raw = b'{"unix":1,"load":[0,0,0],"offenders":[],"top_processes":[]}\n'
            source.write_bytes(raw)
            self.assertEqual(export(source, destination), 1)
            self.assertEqual(source.read_bytes(), raw)
            with self.assertRaises(FileExistsError):
                export(source, destination)
            link = root / "link"
            link.symlink_to(source)
            with self.assertRaises(FileExistsError):
                export(source, link)
            with self.assertRaises(ValueError):
                export(link, root / "invalid")
            self.assertEqual(source.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
