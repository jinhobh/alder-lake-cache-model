# Noise-floor protocol

The held-out list is frozen in `heldout.txt` (see below). Do not use simulator
results to select or replace workloads. Native Phase 0 repeats characterize measurement variability;
model comparisons wait for frozen-model Phase 7 evaluation.

Collect at least ten native measurements per workload/scenario/event per boot
and repeat across at least two boots. Pin the measurement region, keep machine
state identical except for explicitly recorded reboot effects, use user-only
PMU events without multiplexing, and subtract the matched empty-loop baseline.
These measurement operations still need the Phase 3 harness. Negative
baseline-subtracted counts need investigation rather than silent clamping.

Record machine state before each run with `tools/machine_state.sh`. Keep raw
counts, baseline counts, region instruction counts, exact event encoding and
core type alongside results. The noise analyzer accepts one JSONL row for each
event from each native run:

```json
{"workload":"stable-workload-input-id","scenario":"baseline","cpu":"2","prefetch":"off","event":"cpu_core/exact-verified-event/u","value":1234,"run_id":"run-01","machine_state":"state-run-01.json"}
```

`machine_state` resolves relative to the sample file; `cpu` is a logical CPU ID
stored as a string. Use stable run IDs (the same run may provide multiple distinct
events). Repeating a group/run ID within one boot is rejected. A boot ID and git
revision must be present in the machine-state record. Event names above are
placeholders for the format, not verified PMU mappings.

```sh
python3 validation/noise.py native-counts.jsonl --output noise.json --seed 7
```

The report includes per-event median, pooled sample CV, per-boot median/CV,
and a deterministic bootstrap 95% CI for the median. The bootstrap samples
boots and then runs within each boot to retain between-boot variation. Reports
hash the input and referenced machine records and retain the recorded revisions.
Exit status is 0 for sufficient sampling, 2 for insufficient repeats/boots
(the report is still emitted), and 1 for malformed input or I/O errors.

Sampling completeness does not validate experimental controls, user-mode event
semantics, tracer compatibility, or workload coverage. Inspect these separately.
The report's twice-CV percentage is a noise floor for provisional relative
targets; it does not finalize S2–S4. Zero-median events require an absolute
criterion. Final MPKI criteria also require consistent region instruction counts.
Never describe synthetic regression fixtures as measurements.

## Frozen held-out suite

`heldout.txt` is the JSON manifest for **cli-heldout-v1**, frozen on 2026-10-23
without examining simulator results. It selects 16 runnable command workloads:
gzip/bzip2/xz compression and decompression, SHA-256/SHA-512, lexical/numeric
sort, unique counting, AWK aggregation, regex search, tar creation/listing, and
AES-256-CTR encryption. These are modest CLI workloads, with correlated cases;
they do not establish coverage of SPEC CPU2017, graph analytics, or general
multithreaded applications. No licensed benchmark installation is required.

Each workload has the same deterministic 1 MiB (`small`) and 32 MiB (`large`)
text corpus for paired working-set scenarios. The manifest records exact argv,
input sizes and SHA-256 hashes, tool versions and executable hashes, and fixed
locale/thread/options environment. Corpus generator v1 uses fixed integer
arithmetic and fixed-width ASCII. The 32 executions were smoke-checked on the
AMD development host, without timing, PMU counts, or simulator comparisons.

```sh
python3 validation/heldout.py prepare --root /tmp/cache-heldout-v1
python3 validation/heldout.py check --root /tmp/cache-heldout-v1
python3 validation/heldout.py smoke --root /tmp/cache-heldout-v1
python3 validation/heldout.py smoke --root /tmp/cache-heldout-v1 \
  --workload gzip-compress --scenario large
```

Preparation writes generated files under the supplied root; use a dedicated
scratch directory. It requires the frozen toolchain. Checking rejects modified
inputs or changed executable binaries/versions. Preserve that toolchain when
moving to the i7-12700K; do not silently regenerate the freeze for newer tools.
Shared-library versions, kernel and CPU dispatch also affect executed code:
retain their machine-state/package records with measurements. Executable hashes
alone do not identify a complete runtime environment.

The command's entire user-mode execution is the selected region. Preparation,
input verification and Python orchestration are outside that region. Native
PMU and tracer runs must execute the manifest argv directly with the recorded
environment and working directory; do not count or trace the Python wrapper.
Tracer confirmation, matching start/stop boundaries, CPU affinity, ASLR, page
policy, page-cache state and empty-region baseline subtraction remain pending.
The compression inputs and sorted/archive inputs are prepared before counting.
`sort` uses one worker and a 128 MiB memory allowance. `tar-list` deliberately
measures archive metadata traversal rather than payload reads. AWK output order
is unspecified and is not a performance-validation signal.

Do not train mechanisms on these workloads or inspect simulator agreement
until a model is frozen. Scope, input, command or toolchain changes require a
new suite ID, a documented reason independent of simulator errors, and retained
older manifests. Freeze completeness does not pass M0: target-machine tracer
confirmation, repeated native counts across reboots and noise-relative S2–S4
thresholds are still required.
