#!/usr/bin/env python3
"""Capture and validate a synthetic offline trace, retaining failure evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "tracer-smoke checksum=201310208\n"


def sha256(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(argv, output, name, records, timeout):
    record = {'argv': [str(arg) for arg in argv]}
    records[name] = record
    try:
        result = subprocess.run(record['argv'], capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        record['error'] = str(exc)
        raise RuntimeError(f'{name}: {exc}') from exc
    (output / f'{name}.stdout').write_bytes(result.stdout)
    (output / f'{name}.stderr').write_bytes(result.stderr)
    record['returncode'] = result.returncode
    if result.returncode:
        raise RuntimeError(f'{name} failed ({result.returncode}); see {name}.stderr')
    return result.stdout


def parse_counts(text):
    counts = {}
    for label in ("instructions", "data loads", "data stores"):
        match = re.search(r"^\s*(\d+) total " + label + r"$", text, re.MULTILINE)
        if not match or int(match[1]) <= 0:
            raise RuntimeError(f"missing or zero total {label} in basic_counts")
        counts[label] = int(match[1])
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drrun', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True,
                        help='new directory; existing evidence is never overwritten')
    parser.add_argument('--cpu', type=int, required=True)
    parser.add_argument('--cc', default='cc', help='compiler executable (no shell flags)')
    parser.add_argument('--timeout', type=int, default=120, help='seconds per command')
    args = parser.parse_args()
    if args.cpu not in os.sched_getaffinity(0):
        parser.error('CPU is outside the current affinity')
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    drrun = args.drrun.resolve()
    if not drrun.is_file():
        parser.error('--drrun must name an existing executable')
    output = args.output.resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error('--output already exists; choose a new evidence directory')
    records = {}
    manifest = {'schema_version': 1, 'status': 'failed', 'cpu': args.cpu,
                'scope': 'synthetic development smoke; target confirmation still required',
                'physical_addresses': 'not requested; virtual addresses only',
                'region': 'whole user process; PMU region alignment not implemented',
                'source_sha256': sha256(ROOT / 'tracer/smoke.c'),
                'drrun_sha256': sha256(drrun), 'commands': records}
    try:
        call = lambda name, argv: run(argv, output, name, records, args.timeout)
        call('machine-state', [sys.executable, ROOT / 'tools/machine_state.py',
                              'record', '--cpus', str(args.cpu),
                              '--output', output / 'machine-state.json'])
        call('version', [drrun, '-version'])
        call('compile', [args.cc, '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror',
                         ROOT / 'tracer/smoke.c', '-o', output / 'smoke'])
        manifest['binary_sha256'] = sha256(output / 'smoke')
        prefix = ['taskset', '-c', str(args.cpu), 'setarch', platform.machine(), '-R']
        native = call('native', prefix + [output / 'smoke'])
        if native.decode() != EXPECTED:
            raise RuntimeError('native checksum does not match the synthetic workload')
        traces = output / 'traces'
        traces.mkdir()
        traced = call('capture', prefix + [drrun, '-t', 'drmemtrace', '-offline',
                                          '-outdir', traces, '--', output / 'smoke'])
        if native != traced:
            raise RuntimeError('native and traced output differ')
        directories = list(traces.glob('drmemtrace.*.dir'))
        if len(directories) != 1:
            raise RuntimeError('expected exactly one trace directory')
        trace = directories[0]
        call('invariants', [drrun, '-t', 'drmemtrace', '-indir', trace,
                            '-tool', 'invariant_checker'])
        call('counts', [drrun, '-t', 'drmemtrace', '-indir', trace,
                        '-tool', 'basic_counts'])
        manifest['counts'] = parse_counts(
            (output / 'counts.stdout').read_text() + (output / 'counts.stderr').read_text())
        files = [p for p in (trace / 'trace').rglob('*') if p.is_file()]
        if not files or not any(p.stat().st_size for p in files):
            raise RuntimeError('no nonempty canonical trace files')
        manifest['trace_files'] = [{'path': str(p.relative_to(output)),
                                    'bytes': p.stat().st_size, 'sha256': sha256(p)}
                                   for p in sorted(files)]
        manifest['status'] = 'passed'
    except (RuntimeError, OSError, UnicodeError) as exc:
        manifest['error'] = str(exc)
        print(exc, file=sys.stderr)
    finally:
        (output / 'result.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(output / 'result.json')
    return 0 if manifest['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
