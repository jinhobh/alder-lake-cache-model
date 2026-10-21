#!/usr/bin/env python3
"""Record Linux experiment state and apply explicit, reversible controls."""
import argparse
import datetime
import glob
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CONTROL_PATTERNS = (
    r"/sys/devices/system/cpu/smt/control",
    r"/sys/devices/system/cpu/intel_pstate/no_turbo",
    r"/sys/devices/system/cpu/cpufreq/boost",
    r"/sys/devices/system/cpu/cpufreq/policy\d+/scaling_(?:min_freq|max_freq|governor)",
    r"/sys/devices/system/cpu/intel_uncore_frequency/package_\d+_die_\d+/(?:min|max)_freq_khz",
    r"/sys/kernel/mm/transparent_hugepage/(?:enabled|defrag)",
    r"/sys/kernel/mm/hugepages/hugepages-(?:2048|1048576)kB/nr_hugepages",
    r"/proc/irq/\d+/smp_affinity_list",
)
STATE_PATTERNS = (
    "/proc/cmdline", "/proc/version", "/proc/sys/kernel/randomize_va_space",
    "/proc/sys/kernel/perf_event_paranoid", "/proc/sys/kernel/nmi_watchdog",
    "/proc/sys/kernel/random/boot_id", "/proc/meminfo", "/proc/cpuinfo",
    "/sys/devices/system/cpu/{online,offline,isolated,nohz_full}",
    "/sys/devices/system/cpu/smt/{active,control}",
    "/sys/devices/system/cpu/intel_pstate/no_turbo",
    "/sys/devices/system/cpu/cpufreq/boost",
    "/sys/devices/system/cpu/cpu[0-9]*/topology/*",
    "/sys/devices/system/cpu/cpu[0-9]*/microcode/version",
    "/sys/devices/system/cpu/cpu[0-9]*/cache/index*/*",
    "/sys/devices/system/cpu/cpufreq/policy*/*",
    "/sys/devices/system/cpu/intel_uncore_frequency/package_*_die_*/*",
    "/sys/kernel/mm/transparent_hugepage/{enabled,defrag}",
    "/sys/kernel/mm/hugepages/hugepages-*/*",
    "/sys/class/dmi/id/{bios_vendor,bios_version,bios_date,board_vendor,board_name,product_name}",
    "/proc/irq/*/smp_affinity_list", "/proc/irq/*/effective_affinity_list",
    "/proc/interrupts",
)


def read_value(path):
    try:
        return {"status": "ok", "value": Path(path).read_text().strip()}
    except (OSError, UnicodeError) as exc:
        return {"status": "unavailable", "error": str(exc)}


def active_value(value):
    """THP controls list all choices, with brackets around the selected one."""
    match = re.search(r"\[([^]]+)\]", value)
    return match.group(1) if match else value.strip()


def expand_braces(pattern):
    match = re.search(r"\{([^}]+)\}", pattern)
    if not match:
        return [pattern]
    return [pattern[:match.start()] + item + pattern[match.end():]
            for item in match.group(1).split(",")]


def command(argv, cwd=None):
    try:
        result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=15)
        return {"argv": argv, "returncode": result.returncode,
                "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": argv, "error": str(exc)}


def record(cpus, metadata):
    paths = {}
    for pattern in STATE_PATTERNS:
        for expanded in expand_braces(pattern):
            matches = glob.glob(expanded)
            if not matches:
                paths[expanded] = {"status": "unavailable", "error": "path not present"}
            for path in sorted(matches):
                if not Path(path).is_dir():
                    paths[path] = read_value(path)
    return {
        "schema_version": 1,
        "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "measurement_cpus": cpus,
        "process_affinity": sorted(os.sched_getaffinity(0)),
        "uid": os.getuid(), "files": paths,
        "commands": [command(["uname", "-a"]), command(["lscpu", "--json"]),
                     command(["git", "rev-parse", "HEAD"], ROOT),
                     command(["git", "status", "--porcelain"], ROOT),
                     command(["dmidecode", "--type", "memory"])],
        "operator_metadata": metadata,
        "unverified": [
            "SMT sibling inactivity and IRQ activity during the measurement",
            "effective fixed core and ring clocks under load",
            "BIOS settings, DRAM timings and channel/rank population unless independently verified",
            "iGPU/display inactivity and background traffic",
            "native/trace ASLR state: launch both with setarch ARCH -R",
            "prefetch controls and empirical prefetch-off verification",
        ],
    }


def write_json(path, data, exclusive=False):
    path = Path(path)
    if exclusive:
        # Create recovery records without replacing any existing experiment.
        with path.open("x") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    else:
        # Keep the previous complete recovery record if an update is interrupted.
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent,
                                             prefix=path.name + ".", delete=False) as stream:
                temp_name = stream.name
                json.dump(data, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        finally:
            if temp_name and Path(temp_name).exists():
                Path(temp_name).unlink()
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def prepare_changes(settings):
    if not isinstance(settings, dict) or not settings:
        raise ValueError("settings must be a nonempty JSON object of absolute path: value")
    changes = []
    for path, value in settings.items():
        if not any(re.fullmatch(pattern, path) for pattern in CONTROL_PATTERNS):
            raise ValueError(f"control is not allowlisted: {path}")
        if not isinstance(value, str) or not value or any(c in value for c in "\n\r\0"):
            raise ValueError(f"control value must be a nonempty single-line string: {path}")
        before = active_value(Path(path).read_text())
        changes.append({"path": path, "before": before, "requested": value})
    return changes


def set_verified(path, value):
    Path(path).write_text(value + "\n")
    actual = active_value(Path(path).read_text())
    if actual != value:
        raise ValueError(f"readback mismatch for {path}: requested {value!r}, read {actual!r}")


def apply(settings, snapshot):
    changes = prepare_changes(settings)  # Read everything before making changes.
    data = {"schema_version": 1, "boot_id": boot_id(), "changes": changes,
            "state_before": record(None, {}), "status": "prepared"}
    write_json(snapshot, data, exclusive=True)  # Durable recovery data before first write.
    try:
        for change in changes:
            set_verified(change["path"], change["requested"])
        data["status"] = "applied"
    except (OSError, ValueError) as exc:
        data["status"] = "partial_failure"
        data["error"] = str(exc)
        raise
    finally:
        write_json(snapshot, data)


def restore(snapshot):
    data = json.loads(Path(snapshot).read_text())
    if data["boot_id"] != boot_id():
        raise ValueError("snapshot belongs to another boot; refusing stale restoration")
    # Validate all paths and current values before changing anything.
    prepare_changes({item["path"]: item["before"] for item in data["changes"]})
    for item in data["changes"]:
        current = active_value(Path(item["path"]).read_text())
        if current not in (item["before"], item["requested"]):
            raise ValueError(f"control changed independently: {item['path']}")
    for item in reversed(data["changes"]):
        set_verified(item["path"], item["before"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    rec = sub.add_parser("record", help="read-only collection; unavailable fields stay explicit")
    rec.add_argument("--cpus", help="measurement CPU list, e.g. 2,10; does not change affinity")
    rec.add_argument("--metadata", type=Path, help="operator-supplied BIOS/DRAM notes as a JSON object")
    rec.add_argument("--output", type=Path, help="new JSON file; default stdout")
    app = sub.add_parser("apply", help="apply only the explicitly listed controls; usually needs root")
    app.add_argument("--settings", type=Path, required=True)
    app.add_argument("--snapshot", type=Path, required=True, help="new recovery JSON file")
    res = sub.add_parser("restore", help="restore controls from a same-boot snapshot")
    res.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "record":
            metadata = json.loads(args.metadata.read_text()) if args.metadata else {}
            if not isinstance(metadata, dict):
                raise ValueError("metadata must be a JSON object")
            data = record(args.cpus, metadata)
            if args.output:
                write_json(args.output, data, exclusive=True)
            else:
                print(json.dumps(data, indent=2, sort_keys=True))
        elif args.action == "apply":
            apply(json.loads(args.settings.read_text()), args.snapshot)
        else:
            restore(args.snapshot)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"machine_state: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
