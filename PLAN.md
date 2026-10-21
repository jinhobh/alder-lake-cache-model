# PLAN: Validated cache-hierarchy model of the Intel i7-12700K

## Goal

Build the first publicly documented, validated model of the i7-12700K cache
hierarchy, covering both core types (Golden Cove P-cores and the Gracemont
E-cluster) and including hardware prefetchers. The model must predict
per-level cache traffic on workloads it was never tuned on:

- **Prefetchers off:** within measurement noise.
- **Prefetchers on:** within about 10% median error.

The model predicts **event counts** (fills, misses, evictions, writebacks,
coherence transfers). It does not predict cycles. Timing is a gated later
phase (see Phase 8).

## Success criteria

| # | Criterion | Target |
|---|-----------|--------|
| S1 | Microbenchmark fidelity, prefetchers off, P and E cores | Every compared event inside the hardware 95% interval |
| S2 | Held-out workloads, prefetchers off | Per-level MPKI: median error ≤ 5%, worst ≤ 15% |
| S3 | Held-out workloads, prefetchers on | Per-level MPKI: median error ≤ 10% |
| S4 | Relative accuracy on paired scenarios (layout change, working-set change, P-core vs E-core placement) | Direction of change correct in ≥ 95% of pairs; magnitude within 20% |
| S5 | Mechanism documentation | Every modeled mechanism has a written finding and the reproducible experiment that establishes it |
| S6 | Error budget | Every remaining held-out discrepancy is attributed to a named cause; "unexplained" is the smallest category |

The S2–S4 thresholds are provisional. Finalize them at the end of Phase 0, once
hardware run-to-run variation has been measured. Any target tighter than about
2× the measured hardware coefficient of variation is meaningless and must be
restated relative to noise.

**Stretch (S7, portability):** Run the characterization suite on a Raptor Lake
machine. Reach S1–S3 by changing only `hardware/*.json` and the measured model
parameters, with no simulator source changes.

## Non-goals (for now)

- Cycle or latency prediction (Phase 8 decides whether to start this).
- Kernel-mode accesses. Count user mode only, and trace user mode only.
- Two SMT threads running together on one P-core.
- iGPU contention for the L3. Keep the iGPU idle; it shares the L3.
- Wrong-path or speculative accesses. These are acknowledged in the error budget, not modeled.

## Ground rules

1. **No tuning on held-out data.** Choose the held-out workloads in Phase 0 and
   freeze the list. Nobody looks at held-out results until a model version is
   frozen.
2. **Every mechanism must earn its place.** A mechanism is merged only if it
   improves agreement on held-out benchmarks by more than measurement noise.
3. **Facts and hypotheses live in separate files.** `hardware/12700k.json`
   holds measured facts. `models/*.json` holds modeling assumptions. Every
   result records both files plus a git hash.
4. **Every run is reproducible.** A result without its machine-state record
   (Phase 0 checklist) does not count.
5. **Each sim statistic maps to an exact counter.** There is no comparison
   without an entry in the counter mapping table (Phase 3).

## Repository layout

```
hardware/12700k.json        measured machine facts (Phase 1)
models/                     modeling assumptions, one file per model version
tools/probe_cpu.c           CPUID/topology probe
tools/prefetch_ctl.c        read/set/verify prefetcher MSRs (P and E cores)
tools/machine_state.sh      apply and record the machine-control checklist
bench/                      microbenchmarks; each emits a native run and a matching trace
  capacity/  conflict/  inclusion/  stream/  write/  sharing/  slice/
harness/                    PMU programming, region markers, run orchestration
tracer/                     Pin or DynamoRIO client for real workloads
sim/                        the simulator
validation/heldout.txt      frozen held-out workload list
reports/                    generated comparison reports
docs/findings/              one file per established mechanism (S5)
docs/counter_map.md         sim statistic ↔ PMU event ↔ known discrepancies
```

---

## Phase 0: Targets, machine control, noise floor

**Tasks**

- [ ] Write `tools/machine_state.sh` to apply and record:
  - SMT sibling idle (or SMT off), isolated CPUs (`isolcpus`, `nohz_full`), IRQ affinity away from the measurement cores.
  - Turbo off. Fixed core clock and fixed ring clock (prefetch timeliness depends on the core:ring:DRAM ratio).
  - Transparent huge pages set deliberately. Huge page pools reserved (2 MiB and 1 GiB).
  - ASLR off for traced/native pairs (`setarch -R`).
  - Kernel version, microcode, BIOS version and settings, DRAM part, speed, timings, channel/rank population.
- [ ] Pick the held-out set: 15–20 workloads, e.g. a SPEC CPU2017 subset plus GAP. Freeze it in `validation/heldout.txt`.
- [ ] Pick the tracer (Pin or DynamoRIO drcachesim) and confirm it runs on this machine.
- [ ] Measure the noise floor:
  - Run ≥ 10 times per workload under identical state.
  - Repeat across reboots, since physical page assignment changes between boots.
  - Report median, CV and bootstrap 95% CI per event.

**Deliverables:** `machine_state.sh`, frozen held-out list, noise report.

**Exit criteria:** S2–S4 thresholds are finalized relative to the measured noise.

---

## Phase 1: Capture the machine configuration

**Tasks**

- [ ] `tools/probe_cpu.c` pins itself to each logical CPU in turn and records:
  - CPUID vendor, family, model, stepping. Leaf 0x1A core type (P/E).
  - Leaf 4 for each cache: type, level, line size, ways, partitions, sets, sharing (max logical CPUs). EDX bits for inclusiveness and complex indexing.
  - Leaf 0x18 (TLB parameters).
- [ ] Merge with sysfs: `/sys/devices/system/cpu/cpu*/topology/*` and `cache/index*/{shared_cpu_list,size,ways_of_associativity,number_of_sets}`.
- [ ] Emit `hardware/12700k.json` (schema below). Remove hard-coded geometry from the simulator; it now loads this file.

**Expected values (to be confirmed by the probe, never assumed):**

| Structure | Expected | Sharing |
|-----------|----------|---------|
| P-core L1D | 48 KiB, 12-way, 64 sets | per core (2 SMT threads) |
| P-core L1I | 32 KiB | per core |
| P-core L2 | 1.25 MiB, 10-way | per core |
| E-core L1D | 32 KiB | per core |
| E-core L1I | 64 KiB | per core |
| E-cluster L2 | 2 MiB, 16-way | 4 E-cores |
| L3 | 25 MiB, sliced, non-inclusive | all cores + iGPU |

**Deliverables:** `probe_cpu`, `hardware/12700k.json`.

**Exit criteria:** Every modeled cache matches the reported geometry and sharing relationships.

---

## Phase 2: Simulator configurability and trace format

This phase comes before characterization, because Phase 4 needs it to rerun
traces under competing hypotheses.

### Trace record

```c
struct trace_rec {
    uint64_t vaddr;
    uint64_t paddr;     /* required: L2 and L3 indexing and the slice hash are physical */
    uint64_t pc;
    uint32_t size;      /* line-crossing accesses are split into two records */
    uint16_t cpu;       /* logical CPU */
    uint8_t  type;      /* LOAD, STORE, IFETCH, SWPF_T0/T1/T2/NTA, NT_STORE,
                           CLFLUSH, CLFLUSHOPT, CLWB, LOCK_RMW, MARKER */
    uint8_t  flags;     /* split, region id, ... */
};
```

`MARKER` records delimit regions, and they line up exactly with the native
run's PMU start/stop points.

### Physical address handling

- **Microbenchmarks:** allocate from 1 GiB or 2 MiB huge pages, and get PFNs from `/proc/self/pagemap` (requires root).
- **Real workloads with 4 KiB pages:** use the recorded PAs if available. Otherwise the simulator applies a random page-to-frame mapping, runs K seeds, and reports a distribution.

### Configuration

- `hardware/*.json` holds geometry and topology.
- `models/*.json` holds the hypotheses:
  - replacement policy per level (including leader-set layout)
  - inclusion/insertion policy per level (inclusive / non-inclusive / exclusive, fill-on-DRAM-read, insert-clean-victims)
  - slice hash
  - prefetchers (per-prefetcher on/off plus parameters)
  - TLB and page-walk model
- CLI overrides, e.g.:
  ```
  sim --hw hardware/12700k.json --model models/v1.json \
      --set l2.replacement=qlru_h00_m1_r0_u1 --set l3.insert_on_fill=false \
      --warmup 1000000 --measure 10000000 --page-seed 7 trace.bin
  ```

### Statistics

Split counts per level and per core:

- demand load, instruction fetch, RFO / store ownership
- software prefetch, hardware prefetch (per prefetcher)
- fills, silent evictions, dirty writebacks
- coherence: forwards, invalidations, back-invalidations
- page-walk accesses

**Exit criteria:** Rerunning one trace under different assumptions requires no source changes.

---

## Phase 3: Measurement harness and counter mapping

**Tasks**

- [ ] `harness/` programs the PMU directly (or uses perf with explicit `cpu_core/…/` and `cpu_atom/…/` events). Counting is user mode only. Never schedule more events than physical counters, so there is no multiplexing. Each benchmark runs an empty-loop baseline, which is subtracted.
- [ ] `tools/prefetch_ctl.c` sets and reads back prefetcher controls:
  - P-cores: MSR 0x1A4.
  - E-cores: MSRs per Intel's *Hardware Prefetch Control for Intel Atom Cores* (0x1A4 plus 0x1320–0x1323).
- [ ] Verify "off" empirically. With prefetchers off, a sequential stream must show one demand miss per line, and prefetch-request counters must read about zero.
- [ ] Write `docs/counter_map.md`. Prefer fill and request events over retired-load events. Verify every event name and meaning against the Intel perfmon ADL files for each core type separately.

| Sim statistic | P-core event (verify) | E-core event (verify) | Known discrepancies |
|---------------|-----------------------|-----------------------|---------------------|
| L1D fills | L1D.REPLACEMENT | | includes HW prefetch fills |
| L1D miss merged into an in-flight line | MEM_LOAD_RETIRED.FB_HIT | | an untimed model has no in-flight state |
| L2 demand requests, hit/miss | L2_RQSTS.* | | |
| L2 fills | L2_LINES_IN.ALL | | |
| L2 evictions, clean/dirty | L2_LINES_OUT.SILENT / NON_SILENT | | |
| L3 references/misses | LONGEST_LAT_CACHE.REFERENCE / MISS | | prefetch inclusion rules |
| Cross-core transfers | MEM_LOAD_L3_HIT_RETIRED.XSNP_* | | retired loads only |
| Page walks | DTLB_LOAD_MISSES.WALK_COMPLETED | | walker loads also hit the caches |

**Deliverables:** harness, `prefetch_ctl`, `counter_map.md`.

**Exit criteria:** Every counter used later has a documented meaning and a list of known discrepancies with the simulator.

---

## Phase 4: Characterization with prefetchers off

Run every benchmark on one pinned P-core and, separately, on one E-core.
Each benchmark emits a native run and a matching trace.

### 4a. Capacity

- Random dependent pointer chains from 4 KiB to 64 MiB, with 8–16 points per octave. Use extra density near 48 KiB, 1.25 MiB, 2 MiB and 25 MiB, none of which is a power of two.
- Run twice:
  - 1 GiB huge pages, to isolate cache behavior.
  - 4 KiB pages, to expose TLB and page-walk effects.
- Collect latency (cycles/access) and counts in the same run.

### 4b. Replacement policy

- Run nanoBench CacheAnalyzer (patch it for the hybrid PMU if needed). Published results stop at Ice Lake, so these findings are new.
- Test many sets per level. The L3 likely uses set dueling, and a single set may be a leader set with a different policy.
- Candidates: the policy family from the CacheAnalyzer simulator (Tree-PLRU, LRU3PLRU4, QLRU variants, adaptive), plus LRU as a baseline.

### 4c. Inclusion and L3 insertion

- Determine whether DRAM reads fill the L3, and whether clean and dirty L2 victims are inserted into the L3.
- Signature test: one core's effective capacity near the L3 boundary is about 25 MiB if the L3 behaves inclusively, about 26.25 MiB if exclusively, and somewhere in between with selective insertion.
- Check for snoop-filter back-invalidation effects.

### 4d. Slice hash

- If the kernel exposes uncore C-box counters, recover the hash by watching which slice's counter moves. Otherwise, build eviction sets from timing.
- Implement the hash in `models/` and validate it on unseen addresses.

### 4e. Writes

- Store streams and RFOs, dirty eviction and writeback counts, non-temporal stores, CLFLUSH/CLWB.

**Deliverables:** one `docs/findings/*.md` per mechanism, `models/v1.json`, comparison reports.

**Exit criteria:** S1 is met for capacity, conflict, inclusion and write benchmarks on both core types.

---

## Phase 5: Sharing and coherence

| Benchmark | Variants |
|-----------|----------|
| Ping-pong on one line (read/write, write/write) | P–P, E–E (same cluster), P–E |
| Producer/consumer buffer | sizes that fit in L2, in L3, and in neither |
| False sharing | two cores, different words in one line |
| E-cluster shared L2 | E–E pair compared with P–P pair at the same working set |

- [ ] Implement explicit coherence states (MESIF-style, refined by measurement) and transfer paths: core-to-core via L3, and within the E-cluster via the shared L2.
- [ ] Interleaving is enforced by synchronization in these benchmarks. For general multithreaded traces, document the chosen interleaving policy as a known accuracy limit.

**Exit criteria:** S1 is met for the sharing benchmarks.

---

## Phase 6: Prefetchers on

- [ ] Enable one prefetcher at a time, on P and E cores separately. Characterize each one with stride, stream, and spatial patterns:
  - trigger conditions and training length
  - prefetch distance and degree
  - page-boundary behavior
  - which cache level it fills
  - throttling under load
- [ ] Model each prefetcher separately, calibrated from microbenchmarks. Then enable them all together and check for interactions.
- [ ] Record the untimed-model limitation: every prefetch is treated as arriving in time.

**Exit criteria:** S1 is met on prefetcher microbenchmarks, or the residual error is quantified and attributed.

---

## Phase 7: Held-out validation

- [ ] Trace the frozen held-out workloads with the chosen tracer. Each trace must carry PAs or use page-seed simulation.
- [ ] Freeze a model version. Run the held-out workloads with prefetchers off, then on. Evaluate S2, S3 and S4.
- [ ] Build the error budget (S6). Attribute each discrepancy to one of:

| Cause | How to detect |
|-------|---------------|
| Counter semantics | discrepancy follows a documented `counter_map.md` caveat |
| Timing effects (in-flight merges, prefetch timeliness) | FB_HIT-heavy regions; error grows with prefetch activity |
| Physical page mapping | error falls within the page-seed distribution |
| Wrong-path accesses | correlation with branch mispredicts |
| Unmodeled mechanism | none of the above |

**Exit criteria:** S2–S6 are met, or the gap is documented with its causes.

---

## Phase 8: Decision gate and stretch goals

- **Timing layer:** Start only if, after Phase 6, prefetch-on error remains
  above target *and* the error budget attributes it mainly to timeliness. The
  minimal version adds miss-handling limits (MSHRs, fill buffers) and an
  approximate core model. A full out-of-order model is out of scope.
- **S7 portability:** Run Phases 1, 4, 5 and 6 on a Raptor Lake machine, using
  configuration changes only.
- **Publish:** findings, benchmark suite, simulator, and the comparison reports.

---

## Milestones

| Milestone | Contents | Evidence |
|-----------|----------|----------|
| M0 | Machine control, noise floor, frozen held-out list | noise report |
| M1 | Probe and config-driven simulator | sim reads `hardware/12700k.json` |
| M2 | Harness, prefetch control, counter map | `counter_map.md` complete |
| M3 | Prefetch-off characterization, P and E | S1 on 4a–4e, findings docs |
| M4 | Coherence | S1 on sharing benchmarks |
| M5 | Prefetchers | S1 on prefetcher benchmarks |
| M6 | Held-out validation | S2–S6 report |

## Risks

| Risk | Mitigation |
|------|------------|
| Prefetchers can't be fully disabled, or some have no control bit | Verify empirically. If residual prefetching remains, characterize it and model it as always on |
| CacheAnalyzer doesn't support the hybrid PMU | Port its set-selection and PMU code. Fall back to timing-based measurement |
| No uncore counters for slice-hash recovery | Timing-based eviction-set construction |
| 4 KiB page mapping noise swamps the targets | Use huge pages for workloads where possible. Report against the page-seed distribution |
| Overfitting to microbenchmarks | Ground rule 1. Use S4 paired scenarios as an independent check |
| Tracer perturbs the address space between native and traced runs | ASLR off, same binary. Compare region-level, not whole-program, counts |

## Open questions

- **Intended use of the model** (code tuning, cache partitioning, security, teaching). This decides whether S2/S3 (absolute) or S4 (relative) is the headline metric.
- How much of the iGPU and display engine's L3 traffic remains when the system is idle and headless.
- Whether the BIOS exposes prefetcher controls that differ from the MSR view.
