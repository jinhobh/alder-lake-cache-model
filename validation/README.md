# Noise-floor protocol

The held-out list is not frozen yet. Do not use simulator results to select or
replace workloads. Native Phase 0 repeats characterize measurement variability;
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
