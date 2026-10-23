# Project status and milestone evidence

The project has been rescoped to [PLAN.md](../PLAN.md). All research milestones
are pending. This file tracks deliverables, not inferred completion from code
or expected hardware specifications.

| Milestone | Status | Existing evidence / remaining work |
|---|---|---|
| M0 | In progress | Machine-state controls and noise analyzer implemented and fixture-tested; 16-workload CLI suite frozen with paired inputs and tool hashes; DynamoRIO offline synthetic smoke passed on AMD; target P/E tracer confirmation, region alignment and hardware noise report pending |
| M1 | In progress | Per-CPU CPUID/sysfs probe implemented; AMD-host smoke checks and synthetic Intel decoding tests pass; target JSON and simulator configuration loading pending |
| M2 | In progress | Native user-only pinned PMU group library and provenance runner implemented; ten synthetic AMD pairs passed; target P/E semantics, trace-region alignment, prefetch control and counter map pending |
| M3 | Pending | No native/trace characterization pairs or established findings |
| M4 | Pending | Legacy ideal snoops exist; no explicit measured coherence protocol or sharing validation |
| M5 | Pending | No prefetch model or characterization |
| M6 | Pending | No frozen model, held-out results, or attributed error budget |

## Immediate work: Phase 0

1. Implement `tools/machine_state.sh` to apply and record the complete machine
   checklist, including explicit unavailable/unverified settings. Machine-wide
   changes must be deliberate and their prior values recorded.
2. Completed: freeze `cli-heldout-v1` in `validation/heldout.txt`: 16 runnable
   CLI workloads, exact versions/binary hashes and input hashes, paired 1 MiB/32 MiB
   scenarios. All 32 command/scenario combinations smoke-tested on the AMD host.
   Preserve the frozen toolchain for target runs; see `validation/README.md`.
3. Selected DynamoRIO drmemtrace; pinned-build AMD smoke passed checksum,
   offline conversion, invariants and instruction/data coverage checks. See
   [reproduction](../tracer/README.md) and [evidence](tracer-smoke.md). Repeat on
   target P/E cores and align user-only regions with the native PMU harness.
   The native harness foundation now passes a ten-pair AMD API smoke and
   fixture tests; see [harness scope and reproduction](../harness/README.md).
4. Collect at least ten repeats per workload under identical recorded state,
   repeat across reboots, and report median, CV, and bootstrap 95% intervals
   for each event. Phase 0 uses these measurements to establish variability,
   not simulator error or model selection from held-out data.
5. Record finalized S2–S4 thresholds and the noise evidence supporting them.

M0 passes only when that evidence exists. Phase 1 then probes every logical CPU
and merges CPUID with sysfs rather than copying the plan's expected geometry.

## Evidence required for later results

Every comparison must carry hardware and model configurations, git revision,
machine-state record, workload/input and region identity, native repetition
records, trace provenance, and exact counter-map entries. Record physical-address
availability or page seeds and the seed distribution. Keep measured facts,
model hypotheses, and established findings separate.

Freeze and identify model versions before held-out evaluation. Changes informed
by held-out discrepancies cannot be described as independent validation on the
same data. Record known limitations and attribute residuals using the Phase 7
error-budget categories.

## Open decisions

The intended use (code tuning, partitioning, security, or teaching) determines
whether absolute S2/S3 accuracy or paired-scenario S4 accuracy is the headline.
Workload availability, tracer compatibility, BIOS/MSR controls, and background
iGPU/display traffic still require target-machine evidence.
