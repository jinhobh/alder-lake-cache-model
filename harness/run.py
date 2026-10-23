#!/usr/bin/env python3
"""Retain provenance and failures for a synthetic user-only PMU group smoke."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def resolve_pmu(name, cpu, root=Path('/sys/bus/event_source/devices')):
    if name not in ('cpu', 'cpu_core', 'cpu_atom'):
        raise ValueError('PMU must be cpu, cpu_core or cpu_atom')
    if name == 'cpu' and any((root / hybrid).exists() for hybrid in ('cpu_core', 'cpu_atom')):
        raise ValueError('hybrid machines require an explicit cpu_core or cpu_atom PMU')
    path = root / name
    pmu_type = int((path / 'type').read_text().strip())
    if pmu_type < 0 or pmu_type > 0xffffffff:
        raise ValueError('invalid PMU type')
    mask = path / 'cpus'
    cpus = None
    if mask.exists():
        cpus = mask.read_text().strip()
        allowed = set()
        for item in cpus.split(','):
            ends = item.split('-')
            first, last = int(ends[0]), int(ends[-1])
            if len(ends) > 2 or first < 0 or last < first:
                raise ValueError('invalid PMU CPU list')
            allowed.update(range(first, last + 1))
        if cpu not in allowed:
            raise ValueError(f'CPU {cpu} does not belong to {name} ({cpus})')
    elif name in ('cpu_core', 'cpu_atom'):
        raise ValueError('hybrid PMU is missing its CPU list')
    return {'name': name, 'type': pmu_type, 'cpus': cpus,
            'type_path': str(path / 'type')}


def config(text):
    value = int(text, 0)
    if not 0 <= value <= 0xffffffffffffffff:
        raise argparse.ArgumentTypeError('config must fit in uint64')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cpu', type=int, required=True)
    parser.add_argument('--pmu', choices=('cpu', 'cpu_core', 'cpu_atom'), required=True)
    parser.add_argument('--event', type=config, action='append', required=True,
                        help='raw config from verified PMU mapping; repeat for a group')
    parser.add_argument('--counter-limit', type=int, required=True,
                        help='verified physical programmable counter budget for this core')
    parser.add_argument('--repeats', type=int, default=10)
    parser.add_argument('--iterations', type=int, default=1000000)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    if args.cpu not in os.sched_getaffinity(0):
        parser.error('CPU is outside the current affinity')
    if not 1 <= len(args.event) <= args.counter_limit <= 8:
        parser.error('require 1 <= event count <= counter limit <= 8')
    if len(set(args.event)) != len(args.event):
        parser.error('duplicate event configs')
    if not 1 <= args.repeats <= 1000000 or not 1 <= args.iterations <= 10**12 or args.timeout <= 0:
        parser.error('invalid repeats, iterations or timeout')
    output = args.output.resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error('--output already exists')
    result = {'schema_version': 1, 'status': 'failed', 'cpu': args.cpu,
              'events': [hex(event) for event in args.event],
              'counter_limit': args.counter_limit, 'repeats': args.repeats,
              'iterations': args.iterations, 'commands': {},
              'scope': 'synthetic native PMU smoke; no verified cache-event semantics or trace alignment',
              'source_sha256': {p: sha256(ROOT / p) for p in
                                ('harness/pmu.c', 'harness/pmu.h', 'harness/smoke.c', 'harness/run.py')}}

    def call(name, argv):
        record = {'argv': [str(arg) for arg in argv]}
        result['commands'][name] = record
        try:
            completed = subprocess.run(record['argv'], capture_output=True, timeout=args.timeout,
                                       cwd=ROOT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            record['error'] = str(exc)
            raise RuntimeError(f'{name}: {exc}') from exc
        (output / f'{name}.stdout').write_bytes(completed.stdout)
        (output / f'{name}.stderr').write_bytes(completed.stderr)
        record['returncode'] = completed.returncode
        if completed.returncode:
            raise RuntimeError(f'{name} failed ({completed.returncode}); see {name}.stderr')
        return completed.stdout

    try:
        call('machine-state', [sys.executable, ROOT / 'tools/machine_state.py',
                              'record', '--cpus', str(args.cpu),
                              '--output', output / 'machine-state.json'])
        result['pmu'] = resolve_pmu(args.pmu, args.cpu)
        call('compile', [args.cc, '-O2', '-std=c11', '-Wall', '-Wextra', '-Wpedantic',
                         '-Wconversion', '-Werror', ROOT / 'harness/pmu.c',
                         ROOT / 'harness/smoke.c', '-o', output / 'pmu-smoke'])
        result['binary_sha256'] = sha256(output / 'pmu-smoke')
        call('measure', ['setarch', platform.machine(), '-R', output / 'pmu-smoke',
                         args.cpu, result['pmu']['type'], args.counter_limit,
                         args.repeats, args.iterations, *[hex(event) for event in args.event]])
        result['status'] = 'passed'
    except (OSError, ValueError, RuntimeError) as exc:
        result['error'] = str(exc)
        print(exc, file=sys.stderr)
    finally:
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(output / 'result.json')
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
