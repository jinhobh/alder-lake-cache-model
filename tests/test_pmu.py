"""PMU selection and evidence failures, independent of perf permissions."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path('harness/run.py').resolve()
spec = importlib.util.spec_from_file_location('pmu_run', SCRIPT)
pmu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pmu)


class PmuTests(unittest.TestCase):
    def test_explicit_hybrid_pmu_cpu_membership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core = root / 'cpu_core'
            core.mkdir()
            (core / 'type').write_text('17\n')
            with self.assertRaises(ValueError):
                pmu.resolve_pmu('cpu', 0, root)
            (core / 'cpus').write_text('0-3,8-11\n')
            self.assertEqual(pmu.resolve_pmu('cpu_core', 9, root)['type'], 17)
            with self.assertRaises(ValueError):
                pmu.resolve_pmu('cpu_core', 4, root)
            (core / 'cpus').unlink()
            with self.assertRaises(ValueError):
                pmu.resolve_pmu('cpu_core', 0, root)
            with self.assertRaises(ValueError):
                pmu.resolve_pmu('../cpu_core', 0, root)

    def test_existing_evidence_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'result.json'
            marker.write_text('preserve')
            result = self.run_smoke(directory)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(marker.read_text(), 'preserve')

    def run_smoke(self, directory, *extra):
        return subprocess.run([sys.executable, SCRIPT, '--cpu',
                               str(min(os.sched_getaffinity(0))), '--pmu', 'cpu',
                               '--event', '0', '--counter-limit', '1',
                               '--output', str(directory), *extra], capture_output=True)

    def test_compiler_failure_keeps_machine_record_and_manifest(self):
        # cpu is the development host PMU; hybrid-only machines use fixture tests.
        if not Path('/sys/bus/event_source/devices/cpu/type').exists():
            self.skipTest('no nonhybrid cpu PMU')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'failed'
            result = self.run_smoke(output, '--cc', '/bin/false')
            self.assertEqual(result.returncode, 1)
            manifest = json.loads((output / 'result.json').read_text())
            self.assertEqual(manifest['status'], 'failed')
            self.assertEqual(manifest['commands']['compile']['returncode'], 1)
            self.assertNotIn('measure', manifest['commands'])
            self.assertTrue((output / 'machine-state.json').is_file())

    def test_budget_and_duplicate_rejected_before_creating_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'invalid'
            for extra in (('--counter-limit', '0'), ('--event', '1'), ('--event', '0')):
                self.assertEqual(self.run_smoke(output, *extra).returncode, 2)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
