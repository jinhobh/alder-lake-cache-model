#!/usr/bin/env python3
"""Reproduce the frozen CLI workload suite without collecting performance data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

MANIFEST = Path(__file__).with_name('heldout.txt')
ENV = {'LC_ALL': 'C', 'TZ': 'UTC', 'OMP_NUM_THREADS': '1',
       'XZ_DEFAULTS': '', 'XZ_OPT': '', 'GZIP': '', 'BZIP2': '', 'BZIP': ''}
TOOLS = ('gzip', 'bzip2', 'xz', 'sha256sum', 'sha512sum', 'sort', 'uniq',
         'awk', 'rg', 'tar', 'openssl')
SCENARIOS = {'small': 8192, 'large': 262144}


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def environment():
    # Exclude ambient tool options, loader injection and locale settings.
    return {'PATH': os.environ.get('PATH', os.defpath), **ENV}


def inventory():
    result = {}
    for tool in TOOLS:
        executable = shutil.which(tool)
        if executable is None:
            raise ValueError(f'missing executable: {tool}')
        flag = 'version' if tool == 'openssl' else '--version'
        proc = subprocess.run([executable, flag], env=environment(),
                              capture_output=True, stdin=subprocess.DEVNULL, check=True)
        result[tool] = {
            'version': (proc.stderr if tool == 'bzip2' else proc.stdout).decode().splitlines()[0],
            'sha256': digest(Path(executable).resolve()),
        }
    return result


def definitions():
    cases = []
    for tool, level in [('gzip', '-6'), ('bzip2', '-6'), ('xz', '-6')]:
        options = ['-n'] if tool == 'gzip' else ['--threads=1'] if tool == 'xz' else []
        suffix = {'gzip': 'gz', 'bzip2': 'bz2', 'xz': 'xz'}[tool]
        cases.extend([
            {'id': f'{tool}-compress', 'argv': [tool, *options, level, '-c', 'records.txt']},
            {'id': f'{tool}-decompress', 'argv': [tool, '-d', '-c', f'records.txt.{suffix}']},
        ])
    cases.extend([
        {'id': 'sha256', 'argv': ['sha256sum', 'records.txt']},
        {'id': 'sha512', 'argv': ['sha512sum', 'records.txt']},
        {'id': 'sort-lexical', 'argv': ['sort', '--parallel=1', '-S', '128M', 'records.txt']},
        {'id': 'sort-numeric', 'argv': ['sort', '--parallel=1', '-S', '128M', '-n', 'records.txt']},
        {'id': 'uniq-count', 'argv': ['uniq', '-c', 'sorted.txt']},
        {'id': 'awk-aggregate', 'argv': ['awk', '{sum[$2]+=$1} END {for (k in sum) print k, sum[k]}', 'records.txt']},
        {'id': 'regex-search', 'argv': ['rg', '--no-config', '--threads', '1', '--color', 'never', '-c',
                                      '^0[0-9]+ group00[0-7][0-9] .*error', 'records.txt']},
        {'id': 'tar-create', 'argv': ['tar', '--format=ustar', '--mtime=@0', '--owner=0', '--group=0',
                                    '--numeric-owner', '-cf', '-', 'records.txt']},
        {'id': 'tar-list', 'argv': ['tar', '-tf', 'records.tar']},
        {'id': 'aes256-ctr', 'argv': ['openssl', 'enc', '-aes-256-ctr', '-nosalt',
                                    '-K', '01' * 32, '-iv', '02' * 16, '-in', 'records.txt']},
    ])
    return cases


def prepare(root):
    root.mkdir(parents=True, exist_ok=True)
    for scenario, count in SCENARIOS.items():
        directory = root / scenario
        directory.mkdir(exist_ok=True)
        with (directory / 'records.txt').open('wb') as stream:
            for index in range(count):
                # Fixed arithmetic, fixed-width ASCII; no RNG/library-version dependency.
                value = (index * 2654435761 + 1013904223) & 0xffffffff
                row = f'{value % 100000000:08d} group{value % 64:04d} item{index % 4096:04d} '
                row += 'error' if value % 7 == 0 else 'valid'
                stream.write((row.ljust(127, '.') + '\n').encode('ascii'))
        commands = [
            (['gzip', '-n', '-6', '-c', 'records.txt'], 'records.txt.gz'),
            (['bzip2', '-6', '-c', 'records.txt'], 'records.txt.bz2'),
            (['xz', '--threads=1', '-6', '-c', 'records.txt'], 'records.txt.xz'),
            (['sort', '--parallel=1', '-S', '128M', 'records.txt'], 'sorted.txt'),
            (['tar', '--format=ustar', '--mtime=@0', '--owner=0', '--group=0', '--numeric-owner',
              '-cf', '-', 'records.txt'], 'records.tar'),
        ]
        for argv, name in commands:
            with (directory / name).open('wb') as output:
                subprocess.run(argv, cwd=directory, env=environment(), stdout=output, check=True)


def inputs(root):
    names = ('records.txt', 'records.txt.gz', 'records.txt.bz2', 'records.txt.xz',
             'sorted.txt', 'records.tar')
    return {scenario: {name: {'bytes': (root / scenario / name).stat().st_size,
                              'sha256': digest(root / scenario / name)} for name in names}
            for scenario in SCENARIOS}


def verify(root, manifest):
    if manifest['tools'] != inventory():
        raise ValueError('tool versions/binary hashes differ from the freeze; preserve the frozen toolchain')
    if manifest['inputs'] != inputs(root):
        raise ValueError('input bytes differ from the freeze; rerun prepare with the frozen toolchain')
    if manifest['workloads'] != definitions() or manifest['scenarios'] != SCENARIOS:
        raise ValueError('suite definition differs from the freeze')


def run(root, manifest, workload, scenario):
    case = next((case for case in manifest['workloads'] if case['id'] == workload), None)
    if case is None:
        raise ValueError(f'unknown workload: {workload}')
    # Smoke execution only: stdout is discarded, no event counts or timing collected.
    subprocess.run(case['argv'], cwd=root / scenario, env=environment(),
                   stdout=subprocess.DEVNULL, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'check', 'smoke'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--workload', help='one frozen workload ID; default: all')
    parser.add_argument('--scenario', choices=SCENARIOS, help='default: both')
    args = parser.parse_args()
    try:
        manifest = json.loads(MANIFEST.read_text())
        if args.action == 'prepare':
            if manifest['tools'] != inventory():
                raise ValueError('prepare requires the frozen toolchain')
            prepare(args.root)
        verify(args.root, manifest)
        if args.action == 'smoke':
            for scenario in [args.scenario] if args.scenario else SCENARIOS:
                for workload in [args.workload] if args.workload else [c['id'] for c in manifest['workloads']]:
                    run(args.root, manifest, workload, scenario)
                    print(f'PASS {workload}/{scenario}', flush=True)
        print('Frozen suite inputs and toolchain verified.')
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'heldout: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
