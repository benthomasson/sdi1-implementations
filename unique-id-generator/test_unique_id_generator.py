"""Tests for unique_id_generator module."""

import re
import threading
import time
import pytest

from unique_id_generator import (
    UUIDGenerator, SnowflakeGenerator, TicketServerGenerator,
    FlakeIDGenerator, ULIDGenerator, IDGeneratorCoordinator,
    CROCKFORD_ALPHABET,
)


def make_clock(start_ms=1_710_000_000_000, step_ms=0):
    """Create a deterministic clock function returning seconds."""
    state = {"ms": start_ms}
    def clock():
        t = state["ms"]
        state["ms"] += step_ms
        return t / 1000.0
    return clock


# 1. Snowflake generates unique IDs across 10,000 generations
def test_snowflake_unique_10k():
    gen = SnowflakeGenerator(datacenter_id=0, worker_id=0)
    ids = gen.generate_batch(10_000)
    assert len(set(ids)) == 10_000


# 2. Snowflake IDs are monotonically increasing
def test_snowflake_monotonic():
    gen = SnowflakeGenerator(datacenter_id=0, worker_id=0)
    ids = gen.generate_batch(1000)
    assert ids == sorted(ids)
    assert len(set(ids)) == 1000  # all distinct


# 3. Snowflake parse correctly extracts all fields
def test_snowflake_parse():
    clock = make_clock(start_ms=1_710_000_000_123)
    gen = SnowflakeGenerator(datacenter_id=7, worker_id=12, clock_fn=clock)
    id1 = gen.generate()
    parsed = SnowflakeGenerator.parse(id1)
    assert parsed["datacenter_id"] == 7
    assert parsed["worker_id"] == 12
    assert parsed["sequence"] == 0
    assert parsed["timestamp_ms"] == 1_710_000_000_123


# 4. Snowflake handles sequence overflow (waits for next ms)
def test_snowflake_sequence_overflow():
    call_count = {"n": 0}
    def clock():
        call_count["n"] += 1
        # First 4097 calls return same ms, then advance
        if call_count["n"] <= 4097:
            return 1_710_000_000.000
        return 1_710_000_001.000  # next second

    gen = SnowflakeGenerator(datacenter_id=0, worker_id=0, clock_fn=clock)
    ids = []
    for _ in range(4097):
        ids.append(gen.generate())
    assert len(set(ids)) == 4097
    # Last ID should be from the next timestamp
    parsed_last = SnowflakeGenerator.parse(ids[-1])
    parsed_prev = SnowflakeGenerator.parse(ids[-2])
    assert parsed_last["timestamp_ms"] > parsed_prev["timestamp_ms"]
    assert parsed_last["sequence"] == 0


# 5. Snowflake detects backward clock
def test_snowflake_backward_clock():
    times = iter([1_710_000_001.0, 1_710_000_000.0])
    gen = SnowflakeGenerator(datacenter_id=0, worker_id=0, clock_fn=lambda: next(times))
    gen.generate()
    with pytest.raises(RuntimeError, match="Clock moved backward"):
        gen.generate()


# 6. Snowflake respects datacenter_id and worker_id ranges
def test_snowflake_id_ranges():
    for dc in range(32):
        for w in [0, 31]:
            gen = SnowflakeGenerator(datacenter_id=dc, worker_id=w)
            id1 = gen.generate()
            parsed = SnowflakeGenerator.parse(id1)
            assert parsed["datacenter_id"] == dc
            assert parsed["worker_id"] == w

    with pytest.raises(ValueError):
        SnowflakeGenerator(datacenter_id=32, worker_id=0)
    with pytest.raises(ValueError):
        SnowflakeGenerator(datacenter_id=0, worker_id=32)


# 7. Ticket server with step=2 produces correct interleaved sequences
def test_ticket_server_interleaved():
    ts1 = TicketServerGenerator(step=2, offset=1)
    ts2 = TicketServerGenerator(step=2, offset=2)
    assert ts1.generate() == 1
    assert ts2.generate() == 2
    assert ts1.generate() == 3
    assert ts2.generate() == 4
    assert ts1.generate() == 5
    assert ts2.generate() == 6

    # Also test step=3
    t1 = TicketServerGenerator(step=3, offset=1)
    t2 = TicketServerGenerator(step=3, offset=2)
    t3 = TicketServerGenerator(step=3, offset=3)
    assert t1.generate() == 1
    assert t2.generate() == 2
    assert t3.generate() == 3
    assert t1.generate() == 4


# 8. Ticket server is thread-safe
def test_ticket_server_thread_safety():
    gen = TicketServerGenerator(step=1, offset=1)
    results = []
    lock = threading.Lock()

    def worker():
        ids = [gen.generate() for _ in range(100)]
        with lock:
            results.extend(ids)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 1000
    assert len(set(results)) == 1000  # no duplicates
    assert set(results) == set(range(1, 1001))


# 9. UUID generates valid format strings
def test_uuid_format():
    gen = UUIDGenerator()
    pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
    for _ in range(100):
        uid = gen.generate()
        assert isinstance(uid, str)
        assert pattern.match(uid), f"Invalid UUID: {uid}"


# 10. ULID is 26 characters in Crockford Base32
def test_ulid_format():
    gen = ULIDGenerator()
    valid_chars = set(CROCKFORD_ALPHABET)
    for _ in range(100):
        ulid = gen.generate()
        assert len(ulid) == 26
        assert all(c in valid_chars for c in ulid)


# 11. ULID is lexicographically sortable by time
def test_ulid_sortable():
    clock = make_clock(start_ms=1_710_000_000_000, step_ms=1)
    gen = ULIDGenerator(clock_fn=clock)
    ids = gen.generate_batch(100)
    assert ids == sorted(ids)


# 12. Coordinator distributes across generators round-robin
def test_coordinator_round_robin():
    clock = make_clock(start_ms=1_710_000_000_000)
    generators = [
        SnowflakeGenerator(datacenter_id=0, worker_id=i, clock_fn=clock)
        for i in range(3)
    ]
    coord = IDGeneratorCoordinator(generators)
    ids = coord.generate_batch(9)
    assert len(set(ids)) == 9

    # Verify round-robin by checking worker_id pattern
    for i, sid in enumerate(ids):
        parsed = SnowflakeGenerator.parse(sid)
        assert parsed["worker_id"] == i % 3


# 13. Batch generation produces all unique IDs
def test_batch_unique():
    gen = SnowflakeGenerator(datacenter_id=0, worker_id=0)
    batch = gen.generate_batch(1000)
    assert len(set(batch)) == 1000
    assert batch == sorted(batch)


# 14. Flake ID hex strings are time-sortable
def test_flake_id_sortable():
    clock = make_clock(start_ms=1_710_000_000_000, step_ms=1)
    gen = FlakeIDGenerator(worker_id=1, clock_fn=clock)
    ids = gen.generate_batch(100)
    assert ids == sorted(ids)
    assert all(len(h) == 32 for h in ids)
    assert all(isinstance(h, str) for h in ids)


# 15. IDs from different workers in same millisecond are still unique
def test_different_workers_same_ms_unique():
    clock = make_clock(start_ms=1_710_000_000_000)
    generators = [
        SnowflakeGenerator(datacenter_id=0, worker_id=i, clock_fn=clock)
        for i in range(5)
    ]
    ids = [g.generate() for g in generators]
    assert len(set(ids)) == 5

    # Also test FlakeID
    flake_gens = [
        FlakeIDGenerator(worker_id=i, clock_fn=clock)
        for i in range(5)
    ]
    flake_ids = [g.generate() for g in flake_gens]
    assert len(set(flake_ids)) == 5
