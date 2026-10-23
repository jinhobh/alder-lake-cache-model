"""Failure handling for the tracer evidence runner (no DynamoRIO dependency)."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path('tracer/smoke.py').resolve()
spec = importlib.util.spec_from_file_location('tracer_smoke', SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class TracerTests(unittest.TestCase):
    def test_counts_require_instruction_and_data_coverage(self):
        text = "10 total instructions\n4 total data loads\n2 total data stores\n"
        self.assertEqual(smoke.parse_counts(text)['data loads'], 4)
        for invalid in ('', text.replace('4 total', '0 total'),
                        text.replace('2 total data stores', '')):
            with self.assertRaises(RuntimeError):
                smoke.parse_counts(invalid)

    def test_failed_command_retains_logs_and_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            records = {}
            with self.assertRaises(RuntimeError):
                smoke.run([sys.executable, '-c',
                           'import sys; print("evidence"); sys.exit(7)'],
                          output, 'failure', records, 5)
            self.assertEqual(records['failure']['returncode'], 7)
            self.assertEqual((output / 'failure.stdout').read_text(), 'evidence\n')

    def test_timeout_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            records = {}
            with self.assertRaises(RuntimeError):
                smoke.run([sys.executable, '-c', 'import time; time.sleep(10)'],
                          Path(directory), 'timeout', records, 0.05)
            self.assertIn('error', records['timeout'])

    def test_existing_evidence_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'result.json'
            marker.write_text('preserve')
            result = subprocess.run([sys.executable, SCRIPT, '--drrun', sys.executable,
                                     '--output', directory, '--cpu',
                                     str(min(os.sched_getaffinity(0)))],
                                    capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(marker.read_text(), 'preserve')

    def test_compiler_failure_writes_failed_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'evidence'
            result = subprocess.run([sys.executable, SCRIPT, '--drrun', '/bin/true',
                                     '--cc', '/bin/false', '--output', output,
                                     '--cpu', str(min(os.sched_getaffinity(0)))],
                                    capture_output=True)
            self.assertEqual(result.returncode, 1)
            manifest = json.loads((output / 'result.json').read_text())
            self.assertEqual(manifest['status'], 'failed')
            self.assertEqual(manifest['commands']['compile']['returncode'], 1)
            self.assertNotIn('capture', manifest['commands'])


if __name__ == '__main__':
    unittest.main()
