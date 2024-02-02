"""Controls for the new bounded Drive continuation, without network or games."""

import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import storage_drive_continuation as module


class Controls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.owner = SimpleNamespace(
            work=self.work,
            plan={"deadline_unix": time.time() + 30, "archive_id": "control"},
            amendment={"maximum_download_attempts_per_object": 3, "reuse_pack": 3},
            check=lambda: None,
        )
        self.data = b"actual bounded transport control\n"
        self.row = {
            "drive_file_id": "test_file_id",
            "bytes": len(self.data),
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "git_blob": module.codec.blob_oid(self.data),
        }
        self.drive = module.ContinuedDrive.__new__(module.ContinuedDrive)
        self.drive.owner = self.owner
        self.drive.spool = self.work
        self.drive.objects = {self.row["git_blob"]: self.row}
        self.fetches = []

        def call(operation, **arguments):
            self.fetches.append((operation, arguments))
            return {"download_url": "https://example.invalid/secret?token=opaque"}

        self.drive.bridge = SimpleNamespace(call=call)

    def tearDown(self):
        self.temp.cleanup()

    def download(self, codes, payload=None):
        codes = iter(codes)

        def run(command, **kwargs):
            self.assertEqual(
                command, ["curl", "--config", str(self.work / "download.conf")]
            )
            self.assertEqual(
                (self.work / "download.conf").stat().st_mode & 0o777, 0o600
            )
            self.assertNotIn("insecure", (self.work / "download.conf").read_text())
            code = next(codes)
            (self.work / "download.bin").write_bytes(
                (self.data if payload is None else payload) if code == 0 else b"partial"
            )
            return SimpleNamespace(
                returncode=code,
                stderr=b"curl failure https://example.invalid/secret?token=opaque\n",
            )

        with patch.object(module.subprocess, "run", side_effect=run):
            return self.drive.get_blob(self.row["git_blob"])

    def test_transient_fetch_uses_fresh_reference_then_exact_bytes(self):
        self.assertEqual(self.download([56, 0]), self.data)
        self.assertEqual(len(self.fetches), 2)
        logs = list(self.work.glob("DRIVE_READBACK_2-*.json"))
        self.assertEqual(len(logs), 1)
        self.assertNotIn("token=opaque", logs[0].read_text())
        self.assertEqual(json.loads(logs[0].read_bytes())["partial_bytes"], 7)
        self.assertFalse((self.work / "download.conf").exists())
        self.assertFalse((self.work / "download.bin").exists())

    def test_three_attempt_limit_is_real(self):
        with self.assertRaisesRegex(ValueError, "bounded attempts"):
            self.download([56, 56, 56])
        self.assertEqual(len(self.fetches), 3)
        self.assertEqual(len(list(self.work.glob("DRIVE_READBACK_2-*.json"))), 3)

    def test_permanent_error_has_no_retry(self):
        with self.assertRaises(ValueError):
            self.download([22])
        self.assertEqual(len(self.fetches), 1)

    def test_corruption_is_not_a_transient_retry(self):
        with self.assertRaisesRegex(ValueError, "raw file readback differs"):
            self.download([0], b"wrong bytes")
        self.assertEqual(len(self.fetches), 1)
        self.assertFalse((self.work / "download.conf").exists())

    def test_hash_mismatch_is_rejected(self):
        self.row["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "raw file readback differs"):
            self.download([0])

    def test_real_deadline_prevents_download(self):
        self.owner.plan["deadline_unix"] = time.time() - 1
        with patch.object(module.subprocess, "run") as runner:
            with self.assertRaisesRegex(ValueError, "deadline"):
                self.drive.get_blob(self.row["git_blob"])
            runner.assert_not_called()

    def test_reuse_exact_chunk_without_upload(self):
        self.drive.reuse = [self.row.copy()]
        self.drive.reused_bytes = 0
        self.assertEqual(
            self.drive.put_blob(self.data, "part.bin"), self.row["git_blob"]
        )
        self.assertFalse(self.drive.reuse)
        self.assertEqual(self.drive.reused_bytes, len(self.data))
        self.assertEqual(self.fetches, [])

    def test_changed_recompressed_chunk_rejected(self):
        self.drive.reuse = [self.row.copy()]
        self.drive.reused_bytes = 0
        with self.assertRaisesRegex(ValueError, "existing Drive chunk differs"):
            self.drive.put_blob(b"changed", "part.bin")
        self.assertEqual(len(self.drive.reuse), 1)

    def test_no_extra_body_after_complete_old_checkpoint(self):
        self.drive.reuse = []
        with self.assertRaisesRegex(ValueError, "unexpected extra chunk"):
            self.drive.put_blob(self.data, "control-pack-00003-part-00066.bin")

    def test_scope_guard_runs_on_reused_chunk(self):
        self.drive.reuse = [self.row.copy()]
        self.drive.reused_bytes = 0
        self.owner.check = lambda: (_ for _ in ()).throw(
            ValueError("real scope failure")
        )
        with self.assertRaisesRegex(ValueError, "real scope"):
            self.drive.put_blob(self.data, "part.bin")
        self.assertEqual(len(self.drive.reuse), 1)

    def test_bridge_resumes_ids_and_consumes_one_response(self):
        directory = self.work / "drive-bridge"
        directory.mkdir()
        (directory / "0000405.controller.json").write_text("{}")

        def check():
            request = json.loads((directory / "REQUEST.json").read_bytes())
            self.assertEqual(request["id"], "0000406")
            module.previous.private_json(
                directory / "0000406.response.json", {"id": "0000406", "status": "ok"}
            )

        bridge = module.ContinuedBridge(self.work, check)
        self.assertEqual(
            bridge.call("fetch", file_id="test", expected_bytes=1)["id"], "0000406"
        )
        self.assertFalse((directory / "REQUEST.json").exists())

    def test_unresolved_request_does_not_restart(self):
        directory = self.work / "drive-bridge"
        directory.mkdir()
        request = directory / "REQUEST.json"
        request.write_text('{"id":"0000406"}')
        with self.assertRaisesRegex(ValueError, "unresolved prior"):
            module.ContinuedBridge(self.work, lambda: None)
        self.assertTrue(request.exists())

    def test_controller_diff_only_selects_new_ledger(self):
        root = Path(__file__).resolve().parents[1]
        original = (root / "tools/drive_controller.js").read_text()
        actual = (root / "tools/drive_controller_continuation.js").read_text()
        self.assertEqual(
            actual,
            original.replace(
                "u=w/'DRIVE_ARCHIVE_USAGE.json'",
                "u=w/'DRIVE_CONTINUATION_USAGE_2.json'",
            ),
        )


if __name__ == "__main__":
    unittest.main()
