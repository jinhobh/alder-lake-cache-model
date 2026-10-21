# Machine controls and evidence

`sh tools/machine_state.sh record --cpus 2 --output state.json` is read-only.
It records kernel/boot identity, topology, cache sysfs, microcode, isolation,
SMT, IRQ affinities, frequency controls, THP and huge-page pools, BIOS identity,
DRAM DMI data when accessible, process affinity, and git revision/dirty state.
Missing or inaccessible data remain explicit. It does not certify readiness.

Supply `--metadata notes.json` for operator evidence such as BIOS settings,
DRAM part/speed/timings and channel/rank population. Distinguish measured values
from manual notes. Record state immediately before each measurement; retain it
with the result. Machine records can contain local system details; review them
before publishing.

To change controls, create a JSON object mapping allowlisted absolute control
paths to string values. For example, on a machine exposing these controls:

```json
{
  "/sys/devices/system/cpu/intel_pstate/no_turbo": "1",
  "/sys/kernel/mm/transparent_hugepage/enabled": "never"
}
```

```sh
sudo sh tools/machine_state.sh apply --settings controls.json --snapshot before.json
sudo sh tools/machine_state.sh restore --snapshot before.json
```

Apply reads every prior value, durably creates a new recovery snapshot before
writing controls, and checks readback. A failure can leave partial changes;
restore from that snapshot. Restoration checks boot identity and refuses to
overwrite an independently changed value. Snapshots are trusted local files.
Restoration proceeds in reverse control order; preserve snapshots until it
succeeds. Do not run apply/restore concurrently with another controller.

Controls include SMT, turbo/boost, cpufreq policy min/max/governor, exposed Intel
uncore min/max, THP, 2 MiB/1 GiB huge-page pools, and IRQ affinity lists. Configure
frequency min/max in an order the driver accepts. A fixed configured limit does
not prove a fixed effective frequency. Ring controls may be absent; record the
BIOS setting and verify it separately. Huge-page allocation can be partial;
readback failure is an error, not successful reservation.

CPU boot isolation (`isolcpus`, `nohz_full`), BIOS options, and DRAM settings
require separate provisioning. The tool records their observable state rather
than editing boot configuration. Keep SMT siblings idle or turn SMT off;
verify IRQ/background activity throughout the experiment. IRQ affinity can be
managed or rejected by the kernel and irqbalance can undo manual settings.
Launch both native and traced binaries with `setarch $(uname -m) -R` for scoped
ASLR disabling; a global sysctl value does not establish a process's ASLR state.
Keep the iGPU idle. Prefetch MSR controls and their empirical verification are
separate Phase 3 work.
