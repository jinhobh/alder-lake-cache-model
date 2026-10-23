#define _GNU_SOURCE
#include "pmu.h"
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>

static volatile uint64_t data[8192];
static volatile uint64_t sink;

/* Identical loop scaffolding; the baseline omits only the volatile array load.
 * Allocation/initialization and output happen outside the measurement region. */
static void work(uint64_t iterations, int baseline)
{
    uint64_t sum = 0;
    if (baseline) {
        for (uint64_t i = 0; i < iterations; ++i)
            __asm__ volatile("" : "+r"(sum) : "r"(i) : "memory");
    } else {
        for (uint64_t i = 0; i < iterations; ++i)
            sum += data[i & 8191];
    }
    sink = sum;
}

static uint64_t number(const char *text)
{
    char *end;
    errno = 0;
    uint64_t value = strtoull(text, &end, 0);
    if (errno || !*text || *text == '-' || *end) {
        fprintf(stderr, "invalid unsigned integer: %s\n", text);
        exit(2);
    }
    return value;
}

int main(int argc, char **argv)
{
    if (argc < 7 || argc > 6 + PMU_MAX_EVENTS) {
        fprintf(stderr, "usage: %s CPU PMU_TYPE COUNTER_LIMIT REPEATS ITERATIONS CONFIG...\n", argv[0]);
        return 2;
    }
    uint64_t cpu = number(argv[1]), type = number(argv[2]), limit = number(argv[3]);
    uint64_t repeats = number(argv[4]), iterations = number(argv[5]);
    size_t count = (size_t)(argc - 6);
    if (cpu > INT_MAX || type > UINT_MAX || !limit || limit > PMU_MAX_EVENTS ||
        count > limit || !repeats || !iterations) return 2;
    uint64_t configs[PMU_MAX_EVENTS];
    for (size_t i = 0; i < count; ++i) configs[i] = number(argv[6 + i]);
    for (size_t i = 0; i < 8192; ++i) data[i] = i;
    struct pmu_group group;
    if (pmu_open(&group, (int)cpu, (unsigned)type, configs, count, (size_t)limit) < 0) {
        perror("pmu_open (check PMU/core match, permissions and counter availability)");
        pmu_close(&group);
        return 1;
    }
    int status = 1;
    work(iterations, 0); /* explicit warmup; this smoke is a warm-cache stream */
    for (uint64_t run = 0; run < repeats; ++run) {
        struct pmu_counts counts[2];
        /* Alternate order to expose rather than systematically hide drift. */
        for (int phase = 0; phase < 2; ++phase) {
            int baseline = (phase + (int)(run & 1)) & 1;
            if (pmu_region_begin(&group) < 0) { perror("pmu_region_begin"); goto done; }
            work(iterations, baseline);
            if (pmu_region_end(&group, &counts[baseline]) < 0) {
                perror("pmu_region_end (unscheduled, multiplexed or invalid group)");
                goto done;
            }
        }
        for (size_t i = 0; i < count; ++i) {
            uint64_t measured = counts[0].value[i], baseline = counts[1].value[i];
            /* Signed magnitude avoids both unsigned underflow and int64 overflow. */
            printf("{\"run\":%" PRIu64 ",\"config\":\"0x%" PRIx64 "\","
                   "\"raw\":%" PRIu64 ",\"baseline\":%" PRIu64 ",\"adjusted\":%s%" PRIu64
                   ",\"raw_enabled_ns\":%" PRIu64 ",\"raw_running_ns\":%" PRIu64
                   ",\"baseline_enabled_ns\":%" PRIu64 ",\"baseline_running_ns\":%" PRIu64 "}\n",
                   run, configs[i], measured, baseline, measured < baseline ? "-" : "",
                   measured < baseline ? baseline - measured : measured - baseline,
                   counts[0].enabled, counts[0].running, counts[1].enabled, counts[1].running);
        }
    }
    status = 0;
done:
    pmu_close(&group);
    return status;
}
