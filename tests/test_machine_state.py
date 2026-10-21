"""Exercise recovery semantics without changing any host controls."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("machine_state", "tools/machine_state.py")
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)


class MachineStateTests(unittest.TestCase):
    def test_thp_selection(self):
        self.assertEqual(state.active_value("always [madvise] never"), "madvise")

    def test_disallowed_control(self):
        with self.assertRaises(ValueError):
            state.prepare_changes({"/etc/passwd": "bad"})

    def test_recovery_after_partial_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = [Path(directory) / name for name in ("first", "second")]
            first.write_text("old-a\n")
            second.write_text("old-b\n")
            snapshot = Path(directory) / "snapshot.json"
            real_set = state.set_verified

            def fail_second(path, value):
                if path == str(second):
                    raise OSError("injected failure")
                real_set(path, value)

            with patch.object(state, "CONTROL_PATTERNS", (str(first), str(second))), \
                 patch.object(state, "record", return_value={}), \
                 patch.object(state, "set_verified", side_effect=fail_second):
                with self.assertRaises(OSError):
                    state.apply({str(first): "new-a", str(second): "new-b"}, snapshot)
            self.assertEqual(first.read_text().strip(), "new-a")
            with patch.object(state, "CONTROL_PATTERNS", (str(first), str(second))):
                state.restore(snapshot)
            self.assertEqual(first.read_text().strip(), "old-a")
            self.assertEqual(second.read_text().strip(), "old-b")

    def test_snapshot_collision_prevents_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            control, snapshot = [Path(directory) / name for name in ("control", "snapshot")]
            control.write_text("old")
            snapshot.write_text("preserve")
            with patch.object(state, "CONTROL_PATTERNS", (str(control),)), \
                 patch.object(state, "record", return_value={}):
                with self.assertRaises(FileExistsError):
                    state.apply({str(control): "new"}, snapshot)
            self.assertEqual(control.read_text(), "old")
            self.assertEqual(snapshot.read_text(), "preserve")

    def test_restore_rejects_independent_change_and_other_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            control, snapshot = [Path(directory) / name for name in ("control", "snapshot")]
            control.write_text("old")
            with patch.object(state, "CONTROL_PATTERNS", (str(control),)), \
                 patch.object(state, "record", return_value={}):
                state.apply({str(control): "new"}, snapshot)
                control.write_text("someone-else")
                with self.assertRaisesRegex(ValueError, "independently"):
                    state.restore(snapshot)
                with patch.object(state, "boot_id", return_value="different-boot"):
                    with self.assertRaisesRegex(ValueError, "another boot"):
                        state.restore(snapshot)
            self.assertEqual(control.read_text(), "someone-else")


if __name__ == "__main__":
    unittest.main()
