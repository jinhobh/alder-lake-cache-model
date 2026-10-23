#ifndef CACHE_MODEL_PMU_H
#define CACHE_MODEL_PMU_H
#include <stddef.h>
#include <stdint.h>

#define PMU_MAX_EVENTS 8
struct pmu_group {
    int fd[PMU_MAX_EVENTS];
    uint64_t id[PMU_MAX_EVENTS];
    size_t count;
    uint64_t enabled_before, running_before;
};
struct pmu_counts {
    uint64_t enabled, running;
    uint64_t value[PMU_MAX_EVENTS];
};
/* The caller supplies verified PMU type/configs and physical counter budget.
 * Only the calling thread, pinned to cpu, is counted; children are excluded.
 * All functions return -1 with errno on failure. Close after any open failure. */
int pmu_open(struct pmu_group *, int cpu, unsigned type,
             const uint64_t *configs, size_t count, size_t counter_limit);
int pmu_region_begin(struct pmu_group *);
int pmu_region_end(struct pmu_group *, struct pmu_counts *);
void pmu_close(struct pmu_group *);
/* Decode the perf group ABI, rejecting partial, multiplexed or mismatched data. */
int pmu_decode(const struct pmu_group *, const uint64_t *, size_t bytes,
               struct pmu_counts *);
#endif
