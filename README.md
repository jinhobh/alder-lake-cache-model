# Validated i7-12700K cache-hierarchy model

This project aims to build a publicly documented, hardware-validated model of
cache traffic on the Intel i7-12700K, covering Golden Cove P-cores, the
Gracemont E-cluster, and hardware prefetchers. It predicts event counts:
fills, misses, evictions, writebacks, and coherence transfers.

[PLAN.md](PLAN.md) is the authoritative scope, phased roadmap, success criteria,
and experimental protocol. [Project status](docs/status.md) records what exists
and the evidence still needed to pass each milestone.

The repository currently contains an **unvalidated functional baseline** in
`src/cache_sim.c`. Its regression tests establish software behavior only.
No hardware fidelity, measured configuration, or milestone completion is claimed.

Phase 0 tooling has started: see [machine-state collection and controls](tools/README.md).

## Validation targets

- S1: every compared microbenchmark event within the hardware 95% interval,
  prefetchers off, on both core types.
- S2: held-out per-level MPKI error, prefetchers off: median ≤ 5%, worst ≤ 15%.
- S3: held-out per-level MPKI error, prefetchers on: median ≤ 10%.
- S4: paired-scenario direction correct in ≥ 95% of pairs; magnitude within 20%.
- S5–S6: a reproducible finding for every mechanism and an attributed error budget.

S2–S4 are provisional until Phase 0 measures run-to-run and reboot variation.
Targets tighter than approximately twice the measured coefficient of variation
must be restated relative to noise. Timing is gated by Phase 8; cycle prediction,
kernel accesses, simultaneous P-core SMT siblings, iGPU contention, and
wrong-path accesses are outside the current model scope.

## Evidence rules

Measured facts belong in `hardware/12700k.json`; assumptions belong in
`models/*.json`. Those files will be created when their supporting work exists;
the legacy constants are not measured facts. Every result must identify both
configuration files, the git revision, and the machine-state record.

Freeze 15–20 held-out workloads during Phase 0. Do not inspect held-out results
until a model version is frozen, and do not tune on those results. Every
simulator statistic compared with hardware needs an exact, core-type-specific
PMU mapping. Mechanisms must improve held-out agreement beyond measurement
noise under the frozen-model protocol.

## Roadmap

| Milestone | Work | Required evidence |
|---|---|---|
| M0 | Machine control, frozen held-out set, tracer selection, noise floor | Repeated runs across reboots; finalized noise-relative targets |
| M1 | CPUID/sysfs probe, hardware facts, configurable simulator and trace | Geometry and sharing match the machine; hypotheses change without source edits |
| M2 | User-only PMU harness, verified prefetch controls, counter map | No multiplexing; baseline subtraction; documented event semantics |
| M3 | Prefetch-off capacity, conflict, inclusion, slice and write characterization | S1 on P and E; reproducible findings |
| M4 | Sharing and coherence | S1 on sharing benchmarks |
| M5 | Separate P/E prefetcher characterization and interactions | S1 or quantified, attributed residuals |
| M6 | Frozen-model held-out validation and error budget | S2–S6 met or gaps documented |

Follow Phases 0–8 in [the plan](PLAN.md). Phase 2 configurability precedes
Phase 4 characterization. Timing begins only if prefetch error exceeds target
and the error budget primarily attributes it to timeliness. Raptor Lake
portability is a stretch goal using configuration changes only.

## Run the existing baseline

```sh
make
./cache-sim examples/mixed.trace
make test
```

The baseline still accepts the legacy text trace (`CORE OP ADDRESS SIZE`) and
uses hard-coded geometry, LRU, flat modulo indexing, and ideal serialized snoops.
It does not yet implement the planned binary trace, logical CPU topology,
physical-page seed distributions, configuration loading, prefetchers, TLBs,
or explicit coherence states. See the [legacy reference](docs/legacy-simulator.md)
for its CLI, statistics, assumptions, and limitations.

The planned repository layout is specified in PLAN.md. Current `src/`, `tests/`,
and `examples/` remain usable during migration; directories and measured
artifacts should be added with their implementation and evidence.
