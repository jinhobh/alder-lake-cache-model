/* SPDX-License-Identifier: MIT */
#ifndef CPUID_DECODE_H
#define CPUID_DECODE_H
#include <stdbool.h>
#include <stdint.h>

typedef struct { uint32_t eax, ebx, ecx, edx; } CpuidRegs;
typedef struct {
    unsigned type, level, line_bytes, ways, partitions, max_logical_sharers;
    uint64_t sets, size_bytes;
    bool inclusive, complex_indexing, fully_associative;
} CacheInfo;

static inline unsigned cpuid_family(uint32_t eax) {
    unsigned base = (eax >> 8) & 15u;
    return base == 15 ? base + ((eax >> 20) & 255u) : base;
}
static inline unsigned cpuid_model(uint32_t eax) {
    unsigned family = (eax >> 8) & 15u;
    return ((eax >> 4) & 15u) | ((family == 6 || family == 15) ? ((eax >> 12) & 240u) : 0u);
}
static inline bool decode_cache(CpuidRegs r, CacheInfo *out) {
    *out = (CacheInfo){
        .type = r.eax & 31u, .level = (r.eax >> 5) & 7u,
        .line_bytes = (r.ebx & 4095u) + 1u,
        .partitions = ((r.ebx >> 12) & 1023u) + 1u,
        .ways = ((r.ebx >> 22) & 1023u) + 1u,
        .sets = (uint64_t)r.ecx + 1u,
        .max_logical_sharers = ((r.eax >> 14) & 4095u) + 1u,
        .inclusive = (r.edx & 2u) != 0,
        .complex_indexing = (r.edx & 4u) != 0,
        .fully_associative = (r.eax & 512u) != 0,
    };
    if (!out->type) return false;
    uint64_t per_set = (uint64_t)out->line_bytes * out->partitions * out->ways;
    if (out->sets > UINT64_MAX / per_set) return false;
    out->size_bytes = per_set * out->sets;
    return true;
}
#endif
