"""Black-box regression checks; simulator itself has no runtime dependencies."""
import csv
import io
import subprocess
import unittest


def run(trace):
    result = subprocess.run(['./cache-sim', '-'], input=trace, text=True,
                            capture_output=True, check=True)
    rows = {r['cache']: r for r in csv.DictReader(io.StringIO(
        '\n'.join(s for s in result.stdout.splitlines() if not s.startswith('#'))))}
    return rows, result.stdout.splitlines()[-1]


class SimulatorTests(unittest.TestCase):
    def test_cold_and_reuse(self):
        rows, total = run('0 R 4096 8\n0 R 4104 8\n')
        self.assertEqual(rows['P0-L1D']['hits'], '1')
        self.assertEqual(rows['P0-L1D']['misses'], '1')
        self.assertIn('memory_reads=1 ', total)

    def test_split_and_instruction_separation(self):
        rows, total = run('0 R 63 2\n0 I 63 2\n')
        self.assertEqual(rows['P0-L1D']['misses'], '2')
        self.assertEqual(rows['P0-L1I']['misses'], '2')
        self.assertEqual(rows['P0-L2']['hits'], '2')
        self.assertIn('line_accesses=4 ', total)

    def test_e_cluster_and_p_private(self):
        rows, _ = run('8 R 0 1\n9 R 0 1\n0 R 0 1\n1 R 0 1\n')
        self.assertEqual(rows['E-L2']['hits'], '1')
        self.assertEqual(rows['L3']['hits'], '2')

    def test_lru_conflict(self):
        # 64 L1D sets; 13 blocks map to one 12-way set.
        trace = ''.join(f'0 R {i*4096} 1\n' for i in range(13))
        rows, _ = run(trace + '0 R 4096 1\n0 R 0 1\n')
        self.assertEqual(rows['P0-L1D']['hits'], '1')
        self.assertEqual(rows['P0-L1D']['evictions'], '2')
        self.assertEqual(rows['P0-L2']['hits'], '1')

    def test_dirty_eviction(self):
        rows, _ = run(''.join(f'0 W {i*4096} 1\n' for i in range(13)))
        self.assertEqual(rows['P0-L1D']['writebacks'], '1')
        self.assertEqual(rows['P0-L2']['wb_hits'], '1')

    def test_write_invalidation_and_forwarding(self):
        rows, _ = run('0 R 0 1\n1 W 0 1\n0 R 0 1\n')
        self.assertEqual(rows['P0-L1D']['misses'], '2')
        self.assertEqual(rows['P1-L1D']['writebacks'], '1')
        self.assertEqual(rows['P1-L2']['writebacks'], '1')

    def test_writebacks_reach_memory(self):
        # All lines conflict in the flat LLC; exceed every upper cache way count.
        rows, total = run(''.join(f'0 W {i*2621440} 1\n' for i in range(48)))
        self.assertGreater(int(rows['L3']['writebacks']), 0)
        self.assertNotIn('memory_writes=0', total)

    def test_topology(self):
        rows, _ = run('')
        self.assertEqual(len(rows), 34)
        self.assertEqual(sum(int(v['bytes']) for k,v in rows.items() if k.endswith('L2')),12*1024**2)
        self.assertEqual(rows['L3']['bytes'], str(25*1024**2))

    def test_invalid(self):
        for trace in ['12 R 0 1', '0 X 0 1', '0 R 0 0', '0 R -1 1',
                      '0 R 0xffffffffffffffff 2', '0 R 0 1 extra', 'bad']:
            with self.subTest(trace=trace):
                result = subprocess.run(['./cache-sim','-'],input=trace+'\n',text=True,capture_output=True)
                self.assertEqual(result.returncode,2)
                self.assertIn('line 1:',result.stderr)


if __name__ == '__main__':
    unittest.main()
