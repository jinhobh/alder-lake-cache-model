# Legacy functional simulator reference

A C11 functional cache simulator for serialized physical-address traces. No runtime dependencies. Python 3 is used only by the regression tests.

```sh
make
./cache-sim examples/mixed.trace
cat examples/mixed.trace | ./cache-sim -
make test
```

## Trace format

Each row is `CORE OP ADDRESS SIZE`, separated by whitespace. Blank lines and `#` comments are accepted. `CORE` is a physical core: 0–7 are P cores, 8–11 are E cores. `OP` is `R` (load), `W` (store), or `I` (instruction fetch). Addresses are decimal or lowercase `0x` hexadecimal; sizes are positive decimal bytes. Ranges crossing a 64-byte boundary generate one access per touched line. Input order defines execution order. SMT siblings should both map to their physical P-core ID; these IDs do not imply OS CPU numbering. Convert virtual addresses to physical addresses before simulation when physical placement matters.

```text
0 R 0x1000 8
0 W 0x103c 8
8 I 0x8000 16
```

## Geometry

All sizes below use binary units and all lines are 64 bytes.

| Cache | Instances | Capacity each | Ways | Sets |
|---|---:|---:|---:|---:|
| P-core L1D | 8 | 48 KiB | 12 | 64 |
| P-core L1I | 8 | 32 KiB | 8 | 64 |
| P-core unified L2 | 8 | 1.25 MiB | 10 | 2,048 |
| E-core L1D | 4 | 32 KiB | 8 | 64 |
| E-core L1I | 4 | 64 KiB | 8 | 128 |
| E-cluster unified L2 | 1, shared by all 4 E cores | 2 MiB | 16 | 2,048 |
| Shared unified L3 | 1 | 25 MiB | 10 | 40,960 |

Intel's [i7-12700K product specifications](https://www.intel.com/content/www/us/en/products/sku/134594/intel-core-i712700k-processor-25m-cache-up-to-5-00-ghz/specifications.html) establish 8 P cores, 4 E cores, 20 threads, 12 MiB total L2 and 25 MiB L3. Intel's [Optimization Reference Manual](https://cdrdv2-public.intel.com/814198/248966-Optimization-Reference-Manual-V1-049.pdf) describes Golden Cove and Gracemont cache architectures. These are preset modeling parameters, not runtime hardware detection. Confirm geometry on the target machine with CPUID leaf 4 on each core type when validating results. In particular, do not substitute the full Alder Lake die's 30 MiB/12-way LLC for this SKU's 25 MiB/10-way preset.

## Policies and interpretation

* Set index is `line_address % number_of_sets`. Exact LRU replacement, cold initial state, write-back and write-allocate at every level. Full-line writebacks allocate without issuing a read. Partial stores fetch the line on a miss.
* The hierarchy is noninclusive and nonexclusive: lower-level eviction does not invalidate upper copies. An upper-level miss traverses L2, L3, then memory. Dirty evictions propagate downward.
* Ideal serialized snoops forward dirty peer L1D lines to their L2 and dirty peer L2 lines to L3 before lookup. Stores invalidate other cores' L1 copies, all L1I copies, and other L2 domains. This models coherence effects on residency and traffic without implementing MESI states, ownership messages, or coherence timing. Self-modifying code and concurrent instruction/data synchronization are outside scope.
* CSV hits/misses count lookups caused by demand accesses (including demand misses forwarded from an upper cache). `wb_hits`/`wb_misses` count incoming writebacks separately. `writebacks` includes dirty evictions and dirty snoop forwarding; invalidations are not counted as capacity evictions. Miss rate is local misses divided by demand lookups.
* The final comment reports trace records, demand line accesses, memory line reads, and memory line writes. Each transfer is 64 bytes. Dirty lines remain resident at trace end; memory writes count traffic during execution, not a final drain.

This is a locality and traffic model, not a cycle-accurate prediction. It omits prefetching, TLBs, virtual translation, speculative accesses, micro-op caches, out-of-order execution, bandwidth, MSHRs, timing, and Intel's undocumented replacement and LLC slice hash. A flat modulo-indexed L3 preserves capacity and associativity but can produce different conflicts from real hardware. No IPC, execution time, or AMAT is inferred from hit counts. Large traces stream through bounded cache storage; each line access performs ideal snoops across the fixed 12-core topology.
