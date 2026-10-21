/* SPDX-License-Identifier: MIT
 * Linux/x86 read-only CPUID + sysfs inventory. No SKU geometry presets. */
#define _GNU_SOURCE
#include <cpuid.h>
#include <ctype.h>
#include <errno.h>
#include <glob.h>
#include <inttypes.h>
#include <limits.h>
#include <sched.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "cpuid_decode.h"

static FILE *output;
static bool complete = true;

static void string(const char *value) {
    fputc('"', output);
    for (const unsigned char *p = (const unsigned char *)value; *p; ++p) {
        if (*p == '"' || *p == '\\') { fputc('\\', output); fputc(*p, output); }
        else if (*p < 32 || *p >= 127) fprintf(output, "\\u%04x", (unsigned)*p);
        else fputc(*p, output);
    }
    fputc('"', output);
}
static bool file_text(const char *path, char *buffer, size_t size) {
    FILE *file = fopen(path, "r");
    if (!file) return false;
    size_t length = fread(buffer, 1, size - 1, file);
    bool ok = !ferror(file) && (length < size - 1 || feof(file));
    fclose(file);
    buffer[length] = '\0';
    while (length && isspace((unsigned char)buffer[length - 1])) buffer[--length] = '\0';
    return ok;
}
static void file_value(const char *path) {
    char buffer[16384];
    if (file_text(path, buffer, sizeof buffer)) string(buffer);
    else fputs("null", output);
}
static CpuidRegs query(unsigned leaf, unsigned subleaf) {
    CpuidRegs r;
    __cpuid_count(leaf, subleaf, r.eax, r.ebx, r.ecx, r.edx);
    return r;
}
static void raw(CpuidRegs r) {
    fprintf(output, "{\"eax\":%" PRIu32 ",\"ebx\":%" PRIu32 ",\"ecx\":%" PRIu32 ",\"edx\":%" PRIu32 "}",
            r.eax, r.ebx, r.ecx, r.edx);
}
static void identity(char vendor[13], char brand[49], unsigned *maximum, unsigned *extended) {
    CpuidRegs r = query(0, 0);
    *maximum = r.eax;
    memcpy(vendor, &r.ebx, 4); memcpy(vendor + 4, &r.edx, 4); memcpy(vendor + 8, &r.ecx, 4);
    vendor[12] = '\0';
    *extended = query(0x80000000u, 0).eax;
    memset(brand, 0, 49);
    if (*extended >= 0x80000004u) {
        for (unsigned i = 0; i < 3; ++i) {
            r = query(0x80000002u + i, 0);
            memcpy(brand + i * 16u, &r.eax, 4); memcpy(brand + i * 16u + 4u, &r.ebx, 4);
            memcpy(brand + i * 16u + 8u, &r.ecx, 4); memcpy(brand + i * 16u + 12u, &r.edx, 4);
        }
    }
}
static void sysfs(unsigned cpu) {
    const char *topology[] = {"physical_package_id", "die_id", "core_id", "cluster_id",
                            "thread_siblings_list", "core_siblings_list", "cluster_cpus_list"};
    const char *cache_fields[] = {"id", "type", "level", "size", "coherency_line_size",
                                "ways_of_associativity", "physical_line_partition", "number_of_sets", "shared_cpu_list"};
    char path[512];
    fputs(",\"sysfs\":{\"topology\":{", output);
    for (size_t i = 0; i < sizeof topology / sizeof *topology; ++i) {
        if (i) fputc(',', output);
        string(topology[i]); fputc(':', output);
        snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%u/topology/%s", cpu, topology[i]);
        file_value(path);
    }
    fputs("},\"caches\":[", output);
    snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%u/cache/index[0-9]*", cpu);
    glob_t matches = {0};
    int result = glob(path, 0, NULL, &matches);
    if (!result) {
        for (size_t i = 0; i < matches.gl_pathc; ++i) {
            if (i) fputc(',', output);
            fputs("{\"path\":", output); string(matches.gl_pathv[i]);
            for (size_t j = 0; j < sizeof cache_fields / sizeof *cache_fields; ++j) {
                fputc(',', output); string(cache_fields[j]); fputc(':', output);
                snprintf(path, sizeof path, "%s/%s", matches.gl_pathv[i], cache_fields[j]);
                file_value(path);
            }
            fputc('}', output);
        }
    }
    fprintf(output, "],\"cache_directory_available\":%s}}", result ? "false" : "true");
    globfree(&matches);
}
static void caches(unsigned maximum, bool intel) {
    bool first = true, terminated = !intel || maximum < 4;
    fputs(",\"cache_parameters\":[", output);
    if (intel && maximum >= 4) {
        for (unsigned i = 0; i < 64; ++i) {
            CpuidRegs r = query(4, i);
            if (!(r.eax & 31u)) { terminated = true; break; }
            if (!first) fputc(',', output);
            first = false;
            fprintf(output, "{\"subleaf\":%u,\"raw\":", i); raw(r);
            CacheInfo c;
            if (!decode_cache(r, &c)) {
                fputs(",\"error\":\"cache size overflow\"}", output); complete = false; continue;
            }
            fprintf(output, ",\"type\":%u,\"level\":%u,\"line_bytes\":%u,\"ways\":%u,\"partitions\":%u,"
                    "\"sets\":%" PRIu64 ",\"size_bytes\":%" PRIu64 ",\"max_logical_sharers\":%u,"
                    "\"inclusive\":%s,\"complex_indexing\":%s,\"fully_associative\":%s}",
                    c.type, c.level, c.line_bytes, c.ways, c.partitions, c.sets, c.size_bytes,
                    c.max_logical_sharers, c.inclusive ? "true" : "false",
                    c.complex_indexing ? "true" : "false", c.fully_associative ? "true" : "false");
        }
    }
    if (!terminated) complete = false;
    fprintf(output, "],\"cache_leaf_available\":%s,\"cache_enumeration_complete\":%s",
            intel && maximum >= 4 ? "true" : "false", terminated ? "true" : "false");
}
static void tlbs(unsigned maximum, bool intel) {
    bool available = intel && maximum >= 0x18;
    fprintf(output, ",\"tlb_leaf_available\":%s,\"tlb_parameters\":[", available ? "true" : "false");
    if (available) {
        CpuidRegs main = query(0x18, 0);
        bool first = true;
        if (main.eax > 256) complete = false;
        for (unsigned i = 0; i <= main.eax && i <= 256; ++i) {
            CpuidRegs r = query(0x18, i);
            // Null subleaves do not terminate leaf 0x18 enumeration.
            if (i && !(r.edx & 31u)) continue;
            if (!first) fputc(',', output);
            first = false;
            fprintf(output, "{\"subleaf\":%u,\"raw\":", i); raw(r);
            fprintf(output, ",\"type\":%u,\"level\":%u,\"page_size_bits\":%u,\"ways\":%u,"
                    "\"sets\":%" PRIu32 ",\"partitioning_encoding\":%u,\"fully_associative\":%s,\"max_logical_sharers\":%u}",
                    r.edx & 31u, (r.edx >> 5) & 7u, r.ebx & 15u, r.ebx >> 16, r.ecx,
                    (r.ebx >> 8) & 7u, r.edx & 256u ? "true" : "false", ((r.edx >> 14) & 4095u) + 1u);
        }
    }
    fputc(']', output);
}
static void probe(void) {
    char vendor[13], brand[49]; unsigned maximum, extended;
    identity(vendor, brand, &maximum, &extended);
    bool intel = !strcmp(vendor, "GenuineIntel");
    CpuidRegs r = maximum >= 1 ? query(1, 0) : (CpuidRegs){0};
    fputs(",\"vendor\":", output); string(vendor);
    fputs(",\"brand\":", output); string(brand);
    fprintf(output, ",\"max_basic_leaf\":%u,\"max_extended_leaf\":%u,\"family\":%u,\"model\":%u,"
            "\"stepping\":%u,\"hypervisor\":%s,\"leaf1\":", maximum, extended,
            cpuid_family(r.eax), cpuid_model(r.eax), r.eax & 15u, r.ecx & (1u << 31) ? "true" : "false");
    raw(r);
    fputs(",\"leaf1a\":", output);
    unsigned core_type = 0;
    if (intel && maximum >= 0x1a) {
        r = query(0x1a, 0); raw(r); core_type = r.eax >> 24;
    } else fputs("null", output);
    fprintf(output, ",\"core_type_id\":%u,\"core_type\":", core_type);
    string(core_type == 0x40 ? "P" : core_type == 0x20 ? "E" : "unknown");
    caches(maximum, intel);
    tlbs(maximum, intel);
}
static int compare_ids(const void *a, const void *b) {
    unsigned left = *(const unsigned *)a, right = *(const unsigned *)b;
    return (left > right) - (left < right);
}
int main(int argc, char **argv) {
    const char *output_path = NULL;
    bool require_target = false;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--require-12700k")) require_target = true;
        else if (!strcmp(argv[i], "--output") && i + 1 < argc && !output_path) output_path = argv[++i];
        else {
            fprintf(stderr, "usage: %s [--require-12700k] [--output NEW.json]\n", argv[0]);
            return !strcmp(argv[i], "--help") ? 0 : 1;
        }
    }
    char vendor[13], brand[49]; unsigned maximum, extended;
    identity(vendor, brand, &maximum, &extended);
    const char *sku = strstr(brand, "i7-12700K");
    if (require_target && (strcmp(vendor, "GenuineIntel") || !sku || (sku[9] && !isspace((unsigned char)sku[9])))) {
        fprintf(stderr, "probe_cpu: expected Intel i7-12700K, found %s / %s\n", vendor, brand);
        return 1;
    }
    glob_t paths = {0};
    if (glob("/sys/devices/system/cpu/cpu[0-9]*", 0, NULL, &paths) || !paths.gl_pathc) {
        fputs("probe_cpu: cannot enumerate sysfs CPUs\n", stderr); globfree(&paths); return 1;
    }
    unsigned *ids = calloc(paths.gl_pathc, sizeof *ids);
    if (!ids) { perror("calloc"); globfree(&paths); return 1; }
    size_t count = 0;
    unsigned largest = 0;
    for (size_t i = 0; i < paths.gl_pathc; ++i) {
        const char *name = strrchr(paths.gl_pathv[i], '/') + 4;
        char *end; unsigned long id = strtoul(name, &end, 10);
        if (*end || id >= INT_MAX) continue;
        ids[count++] = (unsigned)id;
        if (id > largest) largest = (unsigned)id;
    }
    globfree(&paths);
    qsort(ids, count, sizeof *ids, compare_ids);
    // Kernel affinity masks can be larger than the highest visible sysfs CPU.
    size_t capacity = (size_t)largest + 1;
    cpu_set_t *original = NULL;
    size_t mask_bytes = 0;
    while (capacity <= (size_t)INT_MAX) {
        original = CPU_ALLOC(capacity); mask_bytes = CPU_ALLOC_SIZE(capacity);
        if (!original) break;
        if (!sched_getaffinity(0, mask_bytes, original)) break;
        int error = errno; CPU_FREE(original); original = NULL;
        if (error != EINVAL) break;
        capacity *= 2;
    }
    cpu_set_t *single = original ? CPU_ALLOC(capacity) : NULL;
    if (!original || !single) {
        fputs("probe_cpu: cannot allocate/read affinity mask\n", stderr);
        CPU_FREE(original); CPU_FREE(single); free(ids); return 1;
    }
    output = output_path ? fopen(output_path, "wx") : stdout;
    if (!output) { perror(output_path); CPU_FREE(original); CPU_FREE(single); free(ids); return 1; }
    time_t now = time(NULL); char timestamp[32]; struct tm utc;
    gmtime_r(&now, &utc); strftime(timestamp, sizeof timestamp, "%Y-%m-%dT%H:%M:%SZ", &utc);
    fputs("{\"schema_version\":1,\"kind\":\"cpu_probe\",\"recorded_at_utc\":", output); string(timestamp);
    fputs(",\"boot_id\":", output); file_value("/proc/sys/kernel/random/boot_id");
    fputs(",\"online_cpu_list\":", output); file_value("/sys/devices/system/cpu/online");
    fputs(",\"cpus\":[", output);
    for (size_t i = 0; i < count; ++i) {
        unsigned cpu = ids[i];
        if (i) fputc(',', output);
        fprintf(output, "{\"cpu\":%u,\"status\":", cpu);
        char path[256], online[16];
        snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%u/online", cpu);
        if (file_text(path, online, sizeof online) && !strcmp(online, "0")) string("offline");
        else if (!CPU_ISSET_S(cpu, mask_bytes, original)) { string("outside_initial_affinity"); complete = false; }
        else {
            CPU_ZERO_S(mask_bytes, single); CPU_SET_S(cpu, mask_bytes, single);
            if (sched_setaffinity(0, mask_bytes, single)) {
                string("pin_failed"); fputs(",\"error\":", output); string(strerror(errno)); complete = false;
            } else if (sched_getcpu() != (int)cpu) { string("pin_verification_failed"); complete = false; }
            else { string("ok"); probe(); }
        }
        sysfs(cpu);
    }
    bool restored = sched_setaffinity(0, mask_bytes, original) == 0;
    if (!restored) complete = false;
    fprintf(output, "],\"affinity_restored\":%s,\"complete\":%s}\n", restored ? "true" : "false", complete ? "true" : "false");
    int failed = fflush(output) || ferror(output);
    if (output_path && fclose(output)) failed = 1;
    CPU_FREE(original); CPU_FREE(single); free(ids);
    if (failed) { fputs("probe_cpu: output failed\n", stderr); return 1; }
    return complete ? 0 : 2;
}
