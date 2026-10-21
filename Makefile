CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Wpedantic -Wconversion

.PHONY: all test clean
all: cache-sim
cache-sim: src/cache_sim.c
	$(CC) $(CFLAGS) $< -o $@
test: cache-sim
	python3 tests/test_sim.py
clean:
	rm -f cache-sim
