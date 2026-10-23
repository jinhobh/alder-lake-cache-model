#define _GNU_SOURCE
#include "pmu.h"
#include <errno.h>
#include <linux/perf_event.h>
#include <sched.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>

void pmu_close(struct pmu_group *g)
{
    for (size_t i = 0; i < g->count; ++i) {
        if (g->fd[i] >= 0) close(g->fd[i]);
    }
    g->count = 0;
}

int pmu_open(struct pmu_group *g, int cpu, unsigned type,
             const uint64_t *configs, size_t count, size_t counter_limit)
{
    memset(g, 0, sizeof(*g));
    if (cpu < 0 || cpu >= CPU_SETSIZE || !count || count > PMU_MAX_EVENTS ||
        count > counter_limit) { errno = EINVAL; return -1; }
    cpu_set_t allowed, selected;
    if (sched_getaffinity(0, sizeof(allowed), &allowed) < 0) return -1;
    if (!CPU_ISSET((size_t)cpu, &allowed)) { errno = EINVAL; return -1; }
    CPU_ZERO(&selected);
    CPU_SET((size_t)cpu, &selected);
    if (sched_setaffinity(0, sizeof(selected), &selected) < 0) return -1;
    for (size_t i = 0; i < count; ++i) {
        struct perf_event_attr attr = {0};
        attr.size = sizeof(attr);
        attr.type = type;
        attr.config = configs[i];
        attr.disabled = i == 0;
        attr.pinned = i == 0;
        attr.exclude_kernel = 1;
        attr.exclude_hv = 1;
        attr.read_format = PERF_FORMAT_GROUP | PERF_FORMAT_ID |
                           PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
        int leader = i ? g->fd[0] : -1;
        int fd = (int)syscall(SYS_perf_event_open, &attr, 0, cpu, leader,
                             PERF_FLAG_FD_CLOEXEC);
        if (fd < 0) return -1;
        g->fd[g->count++] = fd;
        if (ioctl(fd, PERF_EVENT_IOC_ID, &g->id[i]) < 0) return -1;
    }
    return 0;
}

__attribute__((noinline)) int pmu_region_begin(struct pmu_group *g)
{
    if (!g->count) { errno = EINVAL; return -1; }
    /* RESET clears counts, but not perf's cumulative scheduling times. */
    uint64_t raw[3 + 2 * PMU_MAX_EVENTS];
    ssize_t bytes;
    do { bytes = read(g->fd[0], raw, sizeof(raw)); } while (bytes < 0 && errno == EINTR);
    if (bytes < 0) return -1;
    if ((size_t)bytes != (3 + 2 * g->count) * sizeof(uint64_t) || raw[0] != g->count) {
        errno = EIO; return -1;
    }
    g->enabled_before = raw[1];
    g->running_before = raw[2];
    if (ioctl(g->fd[0], PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP) < 0) return -1;
    return ioctl(g->fd[0], PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP);
}

int pmu_decode(const struct pmu_group *g, const uint64_t *raw, size_t bytes,
               struct pmu_counts *out)
{
    if (!g->count || g->count > PMU_MAX_EVENTS ||
        bytes != (3 + 2 * g->count) * sizeof(uint64_t) || raw[0] != g->count ||
        !raw[1] || raw[1] != raw[2]) { errno = EIO; return -1; }
    struct pmu_counts result = {.enabled = raw[1], .running = raw[2]};
    unsigned seen = 0;
    for (size_t i = 0; i < g->count; ++i) {
        size_t j;
        for (j = 0; j < g->count && raw[4 + 2 * i] != g->id[j]; ++j) {}
        if (j == g->count || (seen & (1U << j))) { errno = EIO; return -1; }
        seen |= 1U << j;
        result.value[j] = raw[3 + 2 * i];
    }
    *out = result;
    return 0;
}

__attribute__((noinline)) int pmu_region_end(struct pmu_group *g, struct pmu_counts *out)
{
    if (!g->count) { errno = EINVAL; return -1; }
    if (ioctl(g->fd[0], PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP) < 0) return -1;
    uint64_t raw[3 + 2 * PMU_MAX_EVENTS];
    ssize_t bytes;
    do { bytes = read(g->fd[0], raw, sizeof(raw)); } while (bytes < 0 && errno == EINTR);
    if (bytes < 0) return -1;
    if ((size_t)bytes < 3 * sizeof(uint64_t) || raw[1] < g->enabled_before ||
        raw[2] < g->running_before) { errno = EIO; return -1; }
    raw[1] -= g->enabled_before;
    raw[2] -= g->running_before;
    return pmu_decode(g, raw, (size_t)bytes, out);
}
