/* Synthetic tracer check; deliberately independent of the held-out suite. */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>

static volatile uint64_t lines[4096];

int main(void)
{
    uint64_t sum = 0;
    for (uint64_t i = 0; i < 4096; ++i)
        lines[i] = i * 3 + 1;
    for (unsigned repeat = 0; repeat < 8; ++repeat)
        for (unsigned i = 0; i < 4096; ++i)
            sum += lines[(i * 17u) % 4096u];
    printf("tracer-smoke checksum=%" PRIu64 "\n", sum);
    return sum == UINT64_C(201310208) ? 0 : 1;
}
