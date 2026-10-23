# Native PMU harness foundation

`pmu.c` is a Linux `perf_event_open` library for **one pinned calling thread**.
It opens an explicitly selected PMU type and raw configs, excludes kernel and
hypervisor execution, does not inherit into children, and uses one pinned event
group. The caller must supply a verified physical programmable-counter budget;
requests beyond that budget are refused. Fixed counters are not assumed to
expand the budget. Open/scheduling failures are errors, with no event fallback
or scaling. Each region requires positive, exactly equal enabled/running times.
The library reads group IDs rather than assuming the kernel's return order.

`pmu_region_begin` resets and enables the group; `pmu_region_end` disables and
reads it. Perf's scheduling times are cumulative even after RESET, so the
library reports differences for each region. Both functions remain named,
non-inlined symbols for future tracer integration. Calls include some user-side
boundary overhead; this is not yet an exact DynamoRIO ROI marker protocol.
The library changes the calling thread's affinity; it does not restore it.
Always call `pmu_close`, including after partial open failure.

## Synthetic smoke

`run.py` compiles the harness, records machine state and source/binary hashes,
disables ASLR with `setarch -R`, and retains command logs and a final manifest
in a **new** evidence directory, including on failure. CPU affinity is applied
inside the binary before counters are opened. On hybrid hardware, `--pmu
cpu_core` or `--pmu cpu_atom` is required; the runner checks the selected CPU
against that PMU's sysfs `cpus` list. On nonhybrid development machines use
`--pmu cpu`. There is no automatic PMU or raw-event translation.

```sh
python3 harness/run.py --help
make pmu-smoke
```

After verifying raw encodings and the physical counter budget for the selected
core, run (replace all capitalized values):

```sh
python3 harness/run.py --cpu CPU --pmu cpu_core \
  --counter-limit VERIFIED_BUDGET --event RAW_CONFIG \
  --repeats 10 --iterations 1000000 --output /tmp/pmu-check-01
```

Repeat `--event` to count several events simultaneously. Only `config` is
supported; events needing `config1/config2`, offcore filters, PEBS, or uncore
PMUs are not supported. Access permissions may require administrative setup;
the runner does not change perf permissions or machine controls.

The synthetic benchmark warms up a 64 KiB volatile stream, then measures an
empty-loop baseline and a stream region for every repetition, alternating their
order. Initialization and output occur outside the regions. `measure.stdout`
contains JSONL with raw counts, baseline counts, signed `adjusted = raw -
baseline` and scheduling times for each region. Negative differences remain
negative; they are never clipped into apparent nonnegative event counts.
The baseline estimates scaffolding overhead, not a proven exact subtraction of
all overhead. Inspect generated code and baseline variance for research runs.

This smoke is not the frozen held-out workload set. Do not feed its adjusted
counts directly to `validation/noise.py`: that format requires workload,
scenario, prefetch state, run and machine-state identity, and nonnegative counts.
A future collector must explicitly define its event/baseline noise policy.

## Evidence and remaining gates

On 2026-10-23 the AMD Ryzen AI 7 350 development host completed ten native
pairs on CPU 0 with PMU `cpu`, type 4, raw config `0x76`, a conservative budget
of one counter, and 1,000,000 iterations. Every raw and baseline region had
positive equal enabled/running time. Local evidence:
`/tmp/cache-model-pmu-smoke-20261023/run-01/`. This establishes the native API
path only; the encoding has no verified cache-event mapping in this project.
It is not i7-12700K evidence, a noise report, or proof of baseline accuracy.

`make test` covers attribute setup, budget enforcement, partial-open cleanup,
per-region scheduling-time differences, reordered IDs, truncated/duplicate/
unknown IDs, multiplexing rejection, hybrid CPU membership and evidence failure
handling, without requiring access to hardware counters.

Still required before Phase 3 completion:

- Align explicit DynamoRIO markers with native PMU regions and validate overhead.
- Verify Intel ADL P/E event encodings and meanings in `docs/counter_map.md`.
- Run native/trace checks on target P and E cores, then repeated measurements
  under controlled state across reboots.
- Implement prefetch controls and empirically verify that prefetchers are off.
