"""Check that the held-out freeze rejects input and toolchain drift."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('heldout', 'validation/heldout.py')
heldout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(heldout)


class HeldoutTests(unittest.TestCase):
    def fixture(self, root):
        for scenario in heldout.SCENARIOS:
            directory = root / scenario
            directory.mkdir()
            for name in ('records.txt', 'records.txt.gz', 'records.txt.bz2',
                         'records.txt.xz', 'sorted.txt', 'records.tar'):
                (directory / name).write_bytes(b'fixture')
        return {'tools': {'fixture': 'version-1'}, 'inputs': heldout.inputs(root),
                'workloads': heldout.definitions(), 'scenarios': heldout.SCENARIOS}

    def test_same_size_input_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.fixture(root)
            with patch.object(heldout, 'inventory', return_value=manifest['tools']):
                heldout.verify(root, manifest)
                (root / 'large' / 'records.txt').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'input bytes differ'):
                    heldout.verify(root, manifest)

    def test_toolchain_drift_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.fixture(root)
            with patch.object(heldout, 'inventory', return_value={'fixture': 'version-2'}):
                with self.assertRaisesRegex(ValueError, 'tool versions/binary hashes differ'):
                    heldout.verify(root, manifest)

    def test_unknown_workload_cannot_execute(self):
        with patch.object(heldout.subprocess, 'run') as execute:
            with self.assertRaisesRegex(ValueError, 'unknown workload'):
                heldout.run(Path('/unused'), {'workloads': heldout.definitions()},
                            'unfrozen-command', 'small')
            execute.assert_not_called()
