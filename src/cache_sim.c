/* SPDX-License-Identifier: MIT */
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LINE 64
#define CORES 12
#define CACHE_COUNT 34

typedef struct { uint64_t tag, age; bool valid, dirty; } Entry;
typedef struct Cache Cache;
struct Cache {
    char name[24]; size_t bytes, sets; unsigned ways;
    Entry *entries; Cache *next;
    uint64_t clock, hits, misses, evictions, writebacks, wb_hits, wb_misses;
};
static Cache caches[CACHE_COUNT], *l1d[CORES], *l1i[CORES], *l2[CORES], *llc;
static unsigned count;
static uint64_t memory_reads, memory_writes, records, accesses;

static Cache *create(const char *name, size_t bytes, unsigned ways, Cache *next) {
    Cache *c = &caches[count++];
    snprintf(c->name, sizeof c->name, "%s", name);
    c->bytes = bytes; c->ways = ways; c->sets = bytes / (LINE * ways); c->next = next;
    c->entries = calloc(c->sets * ways, sizeof *c->entries);
    if (!c->entries) { perror("calloc"); exit(1); }
    return c;
}
static Entry *find(Cache *c, uint64_t block) {
    Entry *set = c->entries + (block % c->sets) * c->ways;
    for (unsigned i = 0; i < c->ways; ++i)
        if (set[i].valid && set[i].tag == block) return &set[i];
    return NULL;
}
/* Writebacks carry a full line and do not fetch it from the next level. */
static void access_cache(Cache *c, uint64_t block, bool write, bool wb) {
    if (!c) { if (wb) ++memory_writes; else ++memory_reads; return; }
    Entry *e = find(c, block);
    if (e) {
        if (wb) ++c->wb_hits; else ++c->hits;
        e->dirty |= write; e->age = ++c->clock; return;
    }
    if (wb) ++c->wb_misses; else ++c->misses;
    if (!wb) access_cache(c->next, block, false, false);
    Entry *set = c->entries + (block % c->sets) * c->ways;
    e = &set[0];
    for (unsigned i = 0; i < c->ways; ++i) {
        if (!set[i].valid) { e = &set[i]; break; }
        if (set[i].age < e->age) e = &set[i];
    }
    if (e->valid) {
        ++c->evictions;
        if (e->dirty) { ++c->writebacks; access_cache(c->next, e->tag, true, true); }
    }
    *e = (Entry){ .tag = block, .age = ++c->clock, .valid = true, .dirty = write };
}
static void snoop(Cache *c, uint64_t block, bool invalidate) {
    Entry *e = find(c, block);
    if (!e) return;
    if (e->dirty) {
        ++c->writebacks; access_cache(c->next, block, true, true); e->dirty = false;
    }
    if (invalidate) e->valid = false;
}
static void reference(unsigned core, char op, uint64_t block) {
    /* Serialized, ideal snoops: forward dirty peer lines before lookup.
       Writes invalidate peer L1s and other L2 domains. This is not MESI timing. */
    for (unsigned i = 0; i < CORES; ++i) {
        if (i != core) snoop(l1d[i], block, op == 'W');
        if (op == 'W') snoop(l1i[i], block, true);
    }
    for (unsigned i = 0; i < CORES; ++i) {
        if (l2[i] == l2[core]) continue;
        if (i > 8) continue; /* E cores share the domain at index 8. */
        snoop(l2[i], block, op == 'W');
    }
    access_cache(op == 'I' ? l1i[core] : l1d[core], block, op == 'W', false);
    ++accesses;
}
static void setup(void) {
    llc = create("L3", 25u * 1024 * 1024, 10, NULL);
    Cache *e_l2 = create("E-L2", 2u * 1024 * 1024, 16, llc);
    for (unsigned i = 0; i < CORES; ++i) {
        char name[24]; bool p = i < 8;
        snprintf(name, sizeof name, "P%u-L2", i);
        l2[i] = p ? create(name, 1280u * 1024, 10, llc) : e_l2;
        snprintf(name, sizeof name, "%c%u-L1D", p ? 'P' : 'E', p ? i : i-8);
        l1d[i] = create(name, (p ? 48u : 32u) * 1024, p ? 12 : 8, l2[i]);
        snprintf(name, sizeof name, "%c%u-L1I", p ? 'P' : 'E', p ? i : i-8);
        l1i[i] = create(name, (p ? 32u : 64u) * 1024, 8, l2[i]);
    }
}
static bool number(const char *s, int base, uint64_t *out) {
    if (!*s || *s == '-' || *s == '+') return false;
    errno = 0; char *end; unsigned long long value = strtoull(s, &end, base);
    if (errno || *end) return false;
    *out = (uint64_t)value; return true;
}
static void report(void) {
    puts("cache,bytes,ways,sets,hits,misses,miss_rate,evictions,writebacks,wb_hits,wb_misses");
    for (unsigned i = 0; i < count; ++i) {
        Cache *c = &caches[i]; uint64_t n = c->hits + c->misses;
        printf("%s,%zu,%u,%zu,%"PRIu64",%"PRIu64",%.6f,%"PRIu64",%"PRIu64",%"PRIu64",%"PRIu64"\n",
            c->name,c->bytes,c->ways,c->sets,c->hits,c->misses,
            n ? (double)c->misses/(double)n : 0.,c->evictions,c->writebacks,c->wb_hits,c->wb_misses);
    }
    printf("# records=%"PRIu64" line_accesses=%"PRIu64" memory_reads=%"PRIu64" memory_writes=%"PRIu64"\n",
        records,accesses,memory_reads,memory_writes);
}
int main(int argc, char **argv) {
    if (argc != 2 || !strcmp(argv[1], "--help")) {
        fprintf(argc == 2 ? stdout : stderr,
            "Usage: %s TRACE|-\nRows: CORE R|W|I ADDRESS SIZE\n"
            "CORE: 0..7 P, 8..11 E; decimal address or 0x hex; size in bytes.\n"
            "Comments begin with #. Output is CSV; caches start cold and are not flushed.\n", argv[0]);
        return argc == 2 ? 0 : 2;
    }
    FILE *f = !strcmp(argv[1], "-") ? stdin : fopen(argv[1], "r");
    if (!f) { perror(argv[1]); return 1; }
    setup(); char buf[4096]; size_t line = 0; int result = 0;
    while (fgets(buf, sizeof buf, f)) {
        ++line;
        if (!strchr(buf, '\n') && !feof(f)) { fprintf(stderr,"line %zu: row too long\n",line); result=2; break; }
        char *comment = strchr(buf, '#'); if (comment) *comment = 0;
        char *fields[5]; unsigned n = 0;
        for (char *s = strtok(buf, " \t\r\n"); s && n < 5; s = strtok(NULL, " \t\r\n")) fields[n++] = s;
        if (!n) continue;
        uint64_t core, addr, size;
        if (n != 4 || !number(fields[0],10,&core) || core >= CORES ||
            strlen(fields[1]) != 1 || !strchr("RWI",fields[1][0]) ||
            !number(fields[2], strncmp(fields[2],"0x",2) == 0 ? 16 : 10,&addr) ||
            !number(fields[3],10,&size) || !size || size-1 > UINT64_MAX-addr) {
            fprintf(stderr,"line %zu: expected CORE R|W|I ADDRESS SIZE (valid nonzero range)\n",line); result=2; break;
        }
        uint64_t last = (addr + size - 1) / LINE;
        for (uint64_t b = addr / LINE;; ++b) { reference((unsigned)core,fields[1][0],b); if (b == last) break; }
        ++records;
    }
    if (ferror(f)) { perror("trace read"); result=1; }
    if (f != stdin) fclose(f);
    if (!result) report();
    for (unsigned i=0;i<count;++i) free(caches[i].entries);
    return result;
}
