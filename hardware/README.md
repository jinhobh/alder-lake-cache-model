# Measured machine facts

There is no `12700k.json` yet: the development host is an AMD system. Do not
copy expected geometry from PLAN.md into a file presented as measured facts.

Build and run the read-only Linux/x86 inventory probe:

```sh
make probe-cpu
./probe-cpu --output host-inventory.json
```

On the target machine, collect the complete inventory alongside its machine
state record. The SKU guard runs before opening the output file:

```sh
./probe-cpu --require-12700k --output hardware/12700k.json
sh tools/machine_state.sh record --output machine-state.json
```

The report records every sysfs logical CPU. Each accessible online CPU is pinned
and verified before CPUID queries. CPUs outside the initial process affinity,
offline CPUs, and pin failures are explicit. Original affinity is restored.
Exit status is 0 for complete online-CPU coverage, 2 for incomplete coverage,
and 1 for usage/I/O/target errors. `complete` concerns CPUID coverage, not
experimental readiness or cache/sysfs agreement. Do not accept an incomplete
report as the target configuration. Containers and taskset can restrict coverage.

Schema version 1 has a top-level `cpus` array. Each successful CPU entry records
vendor, brand, family/model/stepping, hypervisor presence, raw leaf 1 and 0x1A,
core type, decoded leaf 4 cache geometry/flags, and raw/decoded leaf 0x18 TLB
parameters. Leaf 0x18 is scanned through its maximum subleaf, including gaps.
Cache sharing's `max_logical_sharers` is an architectural addressable-ID bound,
not a count of active threads. Use sysfs shared CPU lists to identify instances.
CPUID and sysfs fields are preserved side by side; inconsistencies must be
investigated rather than silently choosing one source. Null sysfs values mean
unavailable. Intel-specific leaves are not interpreted on other vendors.

The register interpretation follows Intel's [CPUID reference, Table 1-2](https://www.intel.com/content/dam/develop/external/us/en/documents/architecture-instruction-set-extensions-programming-reference-737410.pdf).
The probe captures reported geometry and inclusion/indexing bits; actual
replacement policy, slice hash, insertion behavior, and prefetch mechanisms
remain experimental hypotheses. A hypervisor's inventory is not bare-metal
validation. M1 also requires simulator configuration loading, which is pending.
