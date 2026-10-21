#!/usr/bin/env python3
"""Summarize repeated native event counts without consulting simulator results."""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys

GROUP_FIELDS = ("workload", "scenario", "cpu", "prefetch", "event")
BOOT_PATH = "/proc/sys/kernel/random/boot_id"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_samples(path):
    groups = collections.defaultdict(list)
    states = {}
    seen = set()
    with Path(path).open() as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                sample = json.loads(line)
                if not isinstance(sample, dict):
                    raise ValueError("sample must be a JSON object")
                for field in (*GROUP_FIELDS, "run_id", "machine_state"):
                    if not isinstance(sample.get(field), str) or not sample[field].strip():
                        raise ValueError(f"{field} must be a nonempty string")
                if sample["prefetch"] not in ("off", "on"):
                    raise ValueError("prefetch must be off or on")
                value = sample["value"]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError("value must be a finite nonnegative event count")
                state_path = (Path(path).resolve().parent / sample["machine_state"]).resolve()
                if state_path not in states:
                    state = json.loads(state_path.read_text())
                    if state["schema_version"] != 1:
                        raise ValueError("unsupported machine-state schema")
                    boot = state["files"][BOOT_PATH]
                    if boot["status"] != "ok" or not boot["value"]:
                        raise ValueError("machine state must contain a readable boot ID")
                    revisions = [cmd["stdout"] for cmd in state["commands"]
                                 if cmd.get("argv") == ["git", "rev-parse", "HEAD"]
                                 and cmd.get("returncode") == 0 and cmd.get("stdout")]
                    if len(revisions) != 1:
                        raise ValueError("machine state must identify the git revision")
                    states[state_path] = {"path": str(state_path), "sha256": sha256(state_path),
                                          "boot_id": boot["value"], "git_revision": revisions[0]}
                group = tuple(sample[field] for field in GROUP_FIELDS)
                identity = (group, states[state_path]["boot_id"], sample["run_id"])
                if identity in seen:
                    raise ValueError("duplicate run ID for the same group and boot")
                seen.add(identity)
                groups[group].append({"value": float(value), "run_id": sample["run_id"],
                                      "state": states[state_path]})
            except (ValueError, KeyError, TypeError, OSError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    if not groups:
        raise ValueError("no samples")
    return groups, list(states.values())


def cv(values):
    mean = statistics.mean(values)
    return statistics.stdev(values) / mean if len(values) > 1 and mean else None


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bootstrap_median(boots, iterations, rng):
    # Two-stage bootstrap preserves reboot as the outer sampling unit.
    estimates = []
    for _ in range(iterations):
        values = []
        for boot in rng.choices(boots, k=len(boots)):
            values.extend(rng.choices(boot, k=len(boot)))
        estimates.append(statistics.median(values))
    return [percentile(estimates, 0.025), percentile(estimates, 0.975)]


def analyze(path, iterations=5000, seed=0):
    if iterations < 1000:
        raise ValueError("at least 1000 bootstrap iterations are required")
    groups, states = load_samples(path)
    summaries = []
    for group, samples in sorted(groups.items()):
        by_boot = collections.defaultdict(list)
        for sample in samples:
            by_boot[sample["state"]["boot_id"]].append(sample["value"])
        boots = [sorted(values) for _, values in sorted(by_boot.items())]
        values = [sample["value"] for sample in samples]
        coefficient = cv(values)
        median = statistics.median(values)
        reasons = []
        if len(boots) < 2:
            reasons.append("fewer than two boots")
        if any(len(values) < 10 for values in boots):
            reasons.append("fewer than ten repeats in at least one boot")
        # Stable per-group randomness makes results independent of input ordering.
        group_seed = int.from_bytes(hashlib.sha256(json.dumps([seed, group]).encode()).digest(), "big")
        summary = dict(zip(GROUP_FIELDS, group))
        summary.update({
            "runs": len(values), "boots": len(boots), "median": median,
            "mean": statistics.mean(values), "cv": coefficient,
            "bootstrap_median_95ci": bootstrap_median(boots, iterations, random.Random(group_seed)),
            "noise_relative_floor_percent": 200 * coefficient if coefficient is not None and median else None,
            "relative_error_defined": median > 0,
            "per_boot": [{"boot_id": boot, "runs": len(data),
                          "median": statistics.median(data), "cv": cv(data)}
                         for boot, data in sorted(by_boot.items())],
            "sampling_complete": not reasons, "incomplete_reasons": reasons,
        })
        summaries.append(summary)
    return {"schema_version": 1, "kind": "native_noise_floor",
            "input": {"path": str(Path(path).resolve()), "sha256": sha256(path)},
            "bootstrap": {"method": "two-stage boot/run percentile median", "iterations": iterations, "seed": seed},
            "machine_states": sorted(states, key=lambda state: state["path"]),
            "sampling_complete": all(item["sampling_complete"] for item in summaries),
            "thresholds_finalized": False,
            "limitations": ["Sampling completeness does not certify controlled machine state or PMU semantics.",
                            "Counter counts are analyzed directly; MPKI targets require region instruction counts.",
                            "Zero-median events require absolute/noise-relative criteria instead of relative error.",
                            "Finalize S2-S4 manually with recorded evidence; twice CV is a floor, not validation."],
            "groups": summaries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples", type=Path)
    parser.add_argument("--output", type=Path, help="new JSON report; default stdout")
    parser.add_argument("--bootstrap", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    try:
        report = analyze(args.samples, args.bootstrap, args.seed)
        if args.output:
            with args.output.open("x") as stream:
                json.dump(report, stream, indent=2, allow_nan=False)
                stream.write("\n")
        else:
            print(json.dumps(report, indent=2, allow_nan=False))
        return 0 if report["sampling_complete"] else 2
    except (OSError, ValueError) as exc:
        print(f"noise: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
