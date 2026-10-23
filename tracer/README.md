# Tracer selection and synthetic smoke check

Use **DynamoRIO drmemtrace**, with offline traces and its analysis API. This
selects the tracing framework; it does not use drcachesim's cache model as our
model or evaluate the frozen held-out workloads.

DynamoRIO records user-mode instruction/data references including PC, virtual
address and size, with thread/CPU scheduling metadata. Its offline conversion
and invariant checker provide a useful independent trace check. Pin remains an
alternative if target testing exposes incompatibilities; maintaining two trace
pipelines now has no demonstrated benefit.

Official references: [trace format](https://dynamorio.org/sec_drcachesim_format.html),
[offline capture/conversion](https://dynamorio.org/sec_drcachesim_offline.html), and
[physical-address markers](https://dynamorio.org/sec_drcachesim_phys.html).

## Reproduce

The development smoke passed with this pinned upstream build (not a moving
`latest` URL). Download outside the repository; no system install is needed:

```sh
mkdir -p /tmp/cache-tracer
cd /tmp/cache-tracer
curl -fL -o dynamorio.tar.gz https://github.com/DynamoRIO/dynamorio/releases/download/cronbuild-11.91.20741/DynamoRIO-Linux-11.91.20741.tar.gz
printf '%s  %s\n' c3c7f76e9de7e8f1f58bdd1255b1da4579b7c2e114d77a353e78502683d60044 dynamorio.tar.gz | sha256sum -c -
tar -xzf dynamorio.tar.gz
```

From the repository, choose a CPU in the process's allowed affinity:

```sh
python3 tracer/smoke.py \
  --drrun /tmp/cache-tracer/DynamoRIO-Linux-11.91.20741/bin64/drrun \
  --cpu 0 --output /tmp/cache-tracer/check-01
```

Requires Linux x86-64, Python 3.11+, a C compiler, `taskset`, and permission to
run `setarch x86_64 -R`. The runner compiles `smoke.c`, pins native and traced
execution to the same logical CPU with ASLR disabled, and compares their
checksums. It captures an offline trace, converts it via `-indir`, runs
`invariant_checker` and `basic_counts`, and requires positive instruction,
data-load and data-store totals. This checks trace integrity and basic access
coverage, not exact per-access fidelity or hardware accuracy.

A new evidence directory contains `result.json`, machine state, binary, trace,
and each command's stdout/stderr. A command failure or timeout is a failure;
existing evidence directories are refused. Do not edit DynamoRIO's internal
trace directory. Keep local evidence outside the checkout. The compact
[development report](../docs/tracer-smoke.md) records the tested build and result.

## Remaining target and integration gates

- Repeat on the **i7-12700K**, separately pinned to a P-core and an E-core, and
  retain both machine-state records. The current AMD smoke cannot close this gate.
- Align explicit region markers with the native PMU harness. This smoke traces
  the whole user process, including startup; it has no PMU region boundaries.
- Implement a Phase 2 importer through DynamoRIO's reader API. Preserve access
  types (including special stores/flushes), PC, sizes, thread identities and
  CPU markers; split line crossings. Periodic CPU markers are not a per-access
  logical-CPU guarantee; pin single-thread checks and document interleaving.
- Physical addresses are **not requested** by this smoke. With `-use_physical`,
  consume translation and unavailable markers explicitly; PFNs can require
  privilege and cached mappings can change. A missing PFN must never silently
  become a physical address of zero. Otherwise use Phase 2 page-seed mapping.
- Validate special instructions, multithreading and native/trace address-space
  correspondence before collecting research traces. No held-out workload was
  traced or compared here.
