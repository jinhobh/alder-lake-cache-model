/* Synthetic CPUID fixtures are not target-machine measurements. */
#include <assert.h>
#include "../tools/cpuid_decode.h"

static CpuidRegs fixture(unsigned type, unsigned level, unsigned ways, unsigned sets, unsigned sharers) {
    return (CpuidRegs){.eax = type | (level << 5) | ((sharers - 1u) << 14),
                       .ebx = 63u | ((ways - 1u) << 22), .ecx = sets - 1u, .edx = 4};
}
int main(void) {
    CacheInfo c;
    assert(decode_cache(fixture(1, 1, 12, 64, 2), &c));
    assert(c.size_bytes == 48u * 1024 && c.ways == 12 && c.max_logical_sharers == 2);
    assert(!c.inclusive && c.complex_indexing && c.line_bytes == 64);
    assert(decode_cache(fixture(3, 2, 10, 2048, 2), &c));
    assert(c.size_bytes == 1280u * 1024 && c.level == 2);
    assert(decode_cache(fixture(3, 2, 16, 2048, 4), &c));
    assert(c.size_bytes == 2u * 1024 * 1024 && c.max_logical_sharers == 4);
    assert(decode_cache(fixture(3, 3, 10, 40960, 32), &c));
    assert(c.size_bytes == 25u * 1024 * 1024 && c.sets == 40960);
    assert(!decode_cache((CpuidRegs){0}, &c));
    assert(!decode_cache((CpuidRegs){.eax = 1, .ebx = UINT32_MAX, .ecx = UINT32_MAX}, &c));
    assert(cpuid_family(0x00090672u) == 6 && cpuid_model(0x00090672u) == 0x97);
    assert(cpuid_family(0x00a60f00u) == 25 && cpuid_model(0x00a60f00u) == 0x60);
    return 0;
}
