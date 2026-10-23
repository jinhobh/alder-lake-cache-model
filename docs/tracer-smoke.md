# Development tracer smoke: 2026-10-23

Selected framework: DynamoRIO drmemtrace (offline).

Host: AMD Ryzen AI 7 350, Linux `7.2.11-arch1-1`, x86-64;
CPU 0 pinned, ASLR disabled for both executions. This is development evidence,
not i7-12700K evidence or a validated measurement-machine configuration.
Machine state and full traces/logs are retained locally in
`/tmp/intel-cache-tracer/smoke-03` (temporary, not a durable archive).

Source checkout started at `a9a504ff47440a396ef97e1487e48e7aaaf54276`;
the smoke source and runner were uncommitted additions during this run.
The committed files and the reproduction command in `tracer/README.md` make
this check repeatable without relying on that temporary directory.

| Item | Result |
|---|---|
| DynamoRIO | 11.91.20741, build 0, tag `cronbuild-11.91.20741` |
| Archive SHA-256 | `c3c7f76e9de7e8f1f58bdd1255b1da4579b7c2e114d77a353e78502683d60044` |
| drrun SHA-256 | `f92d796060b53c1ec14ac97e089edfb29a3ce8bd17c2c011fd763054d10f4b55` |
| smoke.c SHA-256 | `a2781c25ee55cf05dabde2cb7e287f6768de64ef58aeb67dc06b4dce57736b91` |
| Compiled workload SHA-256 | `37132f18e9180d962b8390ccae6617cd08c0b2777d8e43ca3588de6a8722486b` |
| Native/traced output | Both `tracer-smoke checksum=201310208` |
| Invariant checker | `Trace invariant checks passed` |
| Instructions | 340453 |
| Data loads | 61280 |
| Data stores | 16998 |
| Physical addresses | Not requested; virtual only |
| PMU region alignment | Not implemented; whole-process smoke |

Counts include runtime startup and are observations, not regression constants.
No simulator comparison or held-out evaluation was run.

An earlier attempt with release 11.3.0, build 1 (tag `release_11.3.0-1`,
archive SHA-256 `ae02049df5c4daeb82d4087aaa0d38bf58cdd26b38fb6042dccf27cbc32ceed9`)
failed during capture with return code -8 (SIGFPE), with empty stderr. Its
native checksum passed. The cause was not established; this failure does not
establish incompatibility on the Intel target. Local failure evidence is in
`/tmp/intel-cache-tracer/smoke-01`.

Target P/E confirmation, physical-address handling, special-access coverage,
and PMU-aligned markers remain open; see `tracer/README.md`.
