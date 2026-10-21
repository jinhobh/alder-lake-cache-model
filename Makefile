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
test: cache-sim probe-cpu test-cpuid
	./test-cpuid
	python3 -m unittest discover -s tests -v
clean:
	rm -f cache-sim probe-cpu test-cpuid
