CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Wpedantic -Wconversion

.PHONY: all test clean
all: cache-sim probe-cpu
cache-sim: src/cache_sim.c
	$(CC) $(CFLAGS) $< -o $@
probe-cpu: tools/probe_cpu.c tools/cpuid_decode.h
	$(CC) $(CFLAGS) tools/probe_cpu.c -o $@
test-cpuid: tests/test_cpuid.c tools/cpuid_decode.h
	$(CC) $(CFLAGS) $< -o $@
pmu-smoke: harness/smoke.c harness/pmu.c harness/pmu.h
	$(CC) $(CFLAGS) harness/smoke.c harness/pmu.c -o $@
test-pmu: tests/test_pmu.c harness/pmu.c harness/pmu.h
	$(CC) $(CFLAGS) tests/test_pmu.c harness/pmu.c -Wl,--wrap=syscall,--wrap=ioctl,--wrap=read,--wrap=close -o $@
test: cache-sim probe-cpu test-cpuid pmu-smoke test-pmu
	./test-cpuid
	./test-pmu
	python3 -m unittest discover -s tests -v
clean:
	rm -f cache-sim probe-cpu test-cpuid pmu-smoke test-pmu
