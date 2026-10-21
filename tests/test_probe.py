"""Host integration checks; decoded Intel geometry uses synthetic C fixtures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(Path('probe-cpu').exists(), 'build probe-cpu first')
class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(['./probe-cpu'], text=True, capture_output=True)
        if result.returncode not in (0, 2):
            raise AssertionError(result.stderr)
        cls.inventory = json.loads(result.stdout)

    def test_host_inventory_and_parent_affinity(self):
        before = os.sched_getaffinity(0)
        result = subprocess.run(['./probe-cpu'], text=True, capture_output=True)
        self.assertIn(result.returncode, (0, 2), result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['affinity_restored'])
        self.assertEqual(os.sched_getaffinity(0), before)
        cpus = [cpu for cpu in data['cpus'] if cpu['status'] == 'ok']
        self.assertTrue(cpus)
        self.assertEqual(len({cpu['cpu'] for cpu in data['cpus']}), len(data['cpus']))
        for cpu in cpus:
            self.assertIn(cpu['cpu'], before)
            self.assertTrue(cpu['vendor'])
            self.assertIn('thread_siblings_list', cpu['sysfs']['topology'])
            self.assertIsInstance(cpu['cache_parameters'], list)
            if cpu['vendor'] != 'GenuineIntel':
                self.assertFalse(cpu['cache_leaf_available'])
                self.assertEqual(cpu['core_type'], 'unknown')

    def test_restricted_affinity_is_explicitly_incomplete(self):
        allowed = os.sched_getaffinity(0)
        if len(allowed) < 2:
            self.skipTest('requires more than one allowed CPU')
        selected = min(allowed)
        result = subprocess.run(['./probe-cpu'], text=True, capture_output=True,
                                preexec_fn=lambda: os.sched_setaffinity(0, {selected}))
        self.assertEqual(result.returncode, 2, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['complete'])
        self.assertEqual([cpu['cpu'] for cpu in data['cpus'] if cpu['status'] == 'ok'], [selected])
        self.assertIn('outside_initial_affinity', {cpu['status'] for cpu in data['cpus']})

    def test_output_refuses_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'existing.json'
            path.write_text('preserve')
            result = subprocess.run(['./probe-cpu', '--output', str(path)], capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(path.read_text(), 'preserve')

    def test_target_guard_on_other_hardware(self):
        cpu = next(cpu for cpu in self.inventory['cpus'] if cpu['status'] == 'ok')
        if cpu['vendor'] == 'GenuineIntel' and 'i7-12700K' in cpu['brand']:
            self.skipTest('requires a different SKU')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '12700k.json'
            result = subprocess.run(['./probe-cpu', '--require-12700k', '--output', str(path)],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('expected Intel i7-12700K', result.stderr)
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
