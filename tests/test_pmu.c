#define _GNU_SOURCE
#include "../harness/pmu.h"
#include <assert.h>
#include <errno.h>
#include <linux/perf_event.h>
#include <sched.h>
#include <stdarg.h>
#include <stdint.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/ioctl.h>

static int opened, closed, fail_member, enabled, multiplex;
static uint64_t ticks;

long __wrap_syscall(long call, ...)
{
    assert(call == SYS_perf_event_open);
    va_list args;
    va_start(args, call);
    struct perf_event_attr *attr = va_arg(args, struct perf_event_attr *);
    assert(va_arg(args, int) == 0); /* calling thread */
    assert(va_arg(args, int) == sched_getcpu());
    int leader = va_arg(args, int);
    assert(va_arg(args, int) == PERF_FLAG_FD_CLOEXEC);
    va_end(args);
    assert(attr->type == 4 && attr->config == (uint64_t)(opened + 1));
    assert(attr->exclude_kernel && attr->exclude_hv && !attr->inherit);
    assert(attr->read_format == (PERF_FORMAT_GROUP | PERF_FORMAT_ID |
           PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING));
    assert(attr->pinned == (opened == 0) && attr->disabled == (opened == 0));
    assert(leader == (opened ? 100 : -1));
    if (fail_member && opened) { errno = EACCES; return -1; }
    return 100 + opened++;
}

int __wrap_ioctl(int fd, unsigned long request, ...)
{
    va_list args;
    va_start(args, request);
    if (request == PERF_EVENT_IOC_ID) {
        uint64_t *id = va_arg(args, uint64_t *);
        *id = (uint64_t)fd;
    } else {
        assert(fd == 100);
        assert(va_arg(args, int) == PERF_IOC_FLAG_GROUP);
        if (request == PERF_EVENT_IOC_ENABLE) enabled = 1;
        else if (request == PERF_EVENT_IOC_DISABLE) { enabled = 0; ticks += 10; }
        else assert(request == PERF_EVENT_IOC_RESET);
    }
    va_end(args);
    return 0;
}

ssize_t __wrap_read(int fd, void *buffer, size_t bytes)
{
    assert(fd == 100 && !enabled && bytes >= 7 * sizeof(uint64_t));
    uint64_t raw[] = {2, ticks, multiplex ? ticks - 1 : ticks, 20, 101, 30, 100};
    memcpy(buffer, raw, sizeof(raw));
    return sizeof(raw);
}

int __wrap_close(int fd)
{
    assert(fd >= 100 && fd < 102);
    ++closed;
    return 0;
}

int main(void)
{
    cpu_set_t allowed;
    assert(sched_getaffinity(0, sizeof(allowed), &allowed) == 0);
    int cpu = 0;
    while (!CPU_ISSET((size_t)cpu, &allowed)) ++cpu;
    uint64_t configs[] = {1, 2};
    struct pmu_group group;
    assert(pmu_open(&group, cpu, 4, configs, 2, 1) == -1 && !opened);
    fail_member = 1;
    assert(pmu_open(&group, cpu, 4, configs, 2, 2) == -1 && opened == 1);
    pmu_close(&group);
    assert(closed == 1);
    fail_member = opened = closed = 0;
    assert(pmu_open(&group, cpu, 4, configs, 2, 2) == 0);
    struct pmu_counts counts;
    for (int i = 0; i < 2; ++i) {
        assert(pmu_region_begin(&group) == 0);
        assert(pmu_region_end(&group, &counts) == 0);
        assert(counts.enabled == 10 && counts.running == 10);
        assert(counts.value[0] == 30 && counts.value[1] == 20);
    }
    assert(pmu_region_begin(&group) == 0);
    multiplex = 1;
    assert(pmu_region_end(&group, &counts) == -1);
    uint64_t raw[] = {2, 10, 10, 20, 101, 30, 100};
    assert(pmu_decode(&group, raw, sizeof(raw), &counts) == 0);
    assert(pmu_decode(&group, raw, sizeof(raw) - 8, &counts) == -1);
    raw[4] = 100; /* duplicate ID */
    assert(pmu_decode(&group, raw, sizeof(raw), &counts) == -1);
    raw[4] = 999; /* unknown ID */
    assert(pmu_decode(&group, raw, sizeof(raw), &counts) == -1);
    raw[4] = 101;
    raw[0] = 1;
    assert(pmu_decode(&group, raw, sizeof(raw), &counts) == -1);
    raw[0] = 2;
    raw[1] = raw[2] = 0;
    assert(pmu_decode(&group, raw, sizeof(raw), &counts) == -1);
    pmu_close(&group);
    assert(closed == 2);
    return 0;
}
