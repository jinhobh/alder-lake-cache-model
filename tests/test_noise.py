"""Synthetic fixtures exercise noise statistics; none are hardware evidence."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("noise", "validation/noise.py")
noise = importlib.util.module_from_spec(spec)
spec.loader.exec_module(noise)


class NoiseTests(unittest.TestCase):
    def fixture(self, directory, values_by_boot):
        rows = []
        for boot_index, values in enumerate(values_by_boot):
            state_path = Path(directory) / f"state-{boot_index}.json"
            state_path.write_text(json.dumps({
                "schema_version": 1,
                "files": {noise.BOOT_PATH: {"status": "ok", "value": str(boot_index)}},
                "commands": [{"argv": ["git", "rev-parse", "HEAD"],
                              "returncode": 0, "stdout": "fixture-revision"}],
            }))
            for run, value in enumerate(values):
                rows.append({"workload": "fixture", "scenario": "base", "cpu": "0",
                             "prefetch": "off", "event": "explicit-test-event", "value": value,
                             "run_id": str(run), "machine_state": state_path.name})
        path = Path(directory) / "samples.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def test_complete_constant_and_zero_events(self):
        for value in (0, 100):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                path = self.fixture(directory, [[value] * 10, [value] * 10])
                report = noise.analyze(path, 1000)
                group = report["groups"][0]
                self.assertTrue(report["sampling_complete"])
                self.assertFalse(report["thresholds_finalized"])
                self.assertEqual(group["bootstrap_median_95ci"], [value, value])
                self.assertEqual(group["cv"], 0 if value else None)
                self.assertEqual(group["noise_relative_floor_percent"], 0 if value else None)

    def test_bootstrap_captures_between_boot_variation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.fixture(directory, [[100] * 10, [200] * 10])
            first = noise.analyze(path, 1000, 9)
            self.assertEqual(first, noise.analyze(path, 1000, 9))
            group = first["groups"][0]
            self.assertEqual(group["median"], 150)
            self.assertEqual(group["bootstrap_median_95ci"], [100, 200])
            self.assertGreater(group["cv"], 0)
            self.assertEqual([boot["cv"] for boot in group["per_boot"]], [0, 0])

    def test_input_order_does_not_change_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.fixture(directory, [list(range(100, 110)), list(range(200, 210))])
            first = noise.analyze(path, 1000, 9)["groups"]
            path.write_text("\n".join(reversed(path.read_text().splitlines())) + "\n")
            self.assertEqual(first, noise.analyze(path, 1000, 9)["groups"])

    def test_incomplete_sampling(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.fixture(directory, [[10] * 9])
            report = noise.analyze(path, 1000)
            self.assertFalse(report["sampling_complete"])
            self.assertEqual(len(report["groups"][0]["incomplete_reasons"]), 2)

    def test_reject_duplicates_invalid_counts_and_missing_state(self):
        for invalid in ("duplicate", "negative", "missing-state", "nan"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                path = self.fixture(directory, [[10] * 10])
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                if invalid == "duplicate":
                    rows.append(rows[0])
                elif invalid == "negative":
                    rows[0]["value"] = -1
                elif invalid == "nan":
                    rows[0]["value"] = float("nan")
                else:
                    rows[0]["machine_state"] = "absent.json"
                path.write_text("".join(json.dumps(row) + "\n" for row in rows))
                with self.assertRaises(ValueError):
                    noise.analyze(path, 1000)


if __name__ == "__main__":
    unittest.main()
