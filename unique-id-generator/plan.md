# Plan (Iteration 1)

Task: UNIQUE ID GENERATOR
System Design Interview Vol 1 - Chapter 7

OVERVIEW
--------
Implement a unique ID generation system supporting multiple strategies for
generating globally unique, 64-bit, sortable identifiers. The system simulates
a multi-server environment within a single process, where each "server" is a
generator instance with a unique worker ID. The focus is on the trade-offs
between different ID generation approaches: randomness vs. sortability,
simplicity vs. coordination, and time-ordering guarantees.

REQUIREMENTS
------------
1.  Implement a UUIDGenerator that generates standard UUID v4 strings (128-bit,
    random, not sortable). This serves as the baseline for comparison.
2.  Implement a SnowflakeGenerator (Twitter Snowflake-style) that produces 64-bit IDs:
    - Bit layout: 1 bit unused sign | 41 bits timestamp (ms since custom epoch) |
      5 bits datacenter_id | 5 bits worker_id | 12 bits sequence number
    - Custom epoch defaults to 2024-01-01 00:00:00 UTC (configurable).
    - Sequence number resets each millisecond.
    - If sequence overflows (>4095 in same ms), wait until next millisecond.
    - Clock must never go backward; raise an error if detected.
3.  Implement a TicketServerGenerator that simulates a centralized auto-increment
    ticket server with configurable step size for multi-server setups.
    - Server 1 generates: 1, 3, 5, 7, ... (step=2, offset=1)
    - Server 2 generates: 2, 4, 6, 8, ... (step=2, offset=2)
    - Thread-safe counter using a lock.
4.  Implement a FlakeIDGenerator (inspired by Boundary Flake) that produces
    128-bit IDs encoded as hex strings: 64 bits timestamp (ms) + 48 bits worker_id +
    16 bits sequence. Sortable by time when compared as strings.
5.  Implement an IDGeneratorCoordinator that manages multiple generator instances
    (simulating multiple servers) and distributes ID generation requests round-robin.
6.  All generators must implement a common IDGenerator interface with generate() -> int|str
    and generate_batch(n: int) -> list methods.
7.  Implement ID parsing: given a Snowflake ID, extract the timestamp, datacenter_id,
    worker_id, and sequence number.
8.  Implement an ID validation method: check that a generated ID conforms to the
    expected format and constraints.
9.  Guarantee monotonically increasing IDs within a single generator instance.
10. Support configurable time source (inject a clock function) for deterministic testing.
11. Implement a ULID-style generator: 48-bit timestamp (ms) + 80-bit random,
    encoded as a 26-character Crockford Base32 string. Lexicographically sortable.

DATA MODELS
-----------
from abc import ABC, abstractmethod
from typing import Callable, Optional

class IDGenerator(ABC):
    @abstractmethod
    def generate(self) -> int | str: ...

    def generate_batch(self, n: int) -> list[int | str]:
        return [self.generate() for _ in range(n)]

class UUIDGenerator(IDGenerator):
    def generate(self) -> str: ...

class SnowflakeGenerator(IDGenerator):
    def __init__(self, datacenter_id: int, worker_id: int,
                 epoch_ms: int = None, clock_fn: Callable[[], float] = None): ...
    def generate(self) -> int: ...

    @staticmethod
    def parse(snowflake_id: int, epoch_ms: int = None) -> dict:
        """Returns {"timestamp_ms": int, "datacenter_id": int,
                    "worker_id": int, "sequence": int, "datetime": str}"""
        ...

class TicketServerGenerator(IDGenerator):
    def __init__(self, step: int = 1, offset: int = 1): ...
    def generate(self) -> int: ...

class FlakeIDGenerator(IDGenerator):
    def __init__(self, worker_id: int, clock_fn: Callable[[], float] = None): ...
    def generate(self) -> str: ...

class ULIDGenerator(IDGenerator):
    def __init__(self, clock_fn: Callable[[], float] = None): ...
    def generate(self) -> str: ...

class IDGeneratorCoordinator:
    def __init__(self, generators: list[IDGenerator]): ...
    def generate(self) -> int | str: ...
    def generate_batch(self, n: int) -> list[int | str]: ...

API SPECIFICATION
-----------------
# UUID
uuid_gen = UUIDGenerator()
id1 = uuid_gen.generate()  # "550e8400-e29b-41d4-a716-446655440000"

# Snowflake
sf_gen = SnowflakeGenerator(datacenter_id=1, worker_id=5)
id1 = sf_gen.generate()  # 64-bit integer like 7019826505736396801
id2 = sf_gen.generate()  # > id1 (monotonically increasing)

# Parse snowflake
info = SnowflakeGenerator.parse(id1)
# {"timestamp_ms": 1709136000123, "datacenter_id": 1, "worker_id": 5,
#  "sequence": 1, "datetime": "2024-02-28T16:00:00.123Z"}

# Ticket server (simulating 2 servers)
ts1 = TicketServerGenerator(step=2, offset=1)
ts2 = TicketServerGenerator(step=2, offset=2)
assert ts1.generate() == 1
assert ts2.generate() == 2
assert ts1.generate() == 3
assert ts2.generate() == 4

# ULID
ulid_gen = ULIDGenerator()
id1 = ulid_gen.generate()  # "01ARZ3NDEKTSV4RRFFQ69G5FAV"
id2 = ulid_gen.generate()  # > id1 lexicographically

# Coordinator
coord = IDGeneratorCoordinator([
    SnowflakeGenerator(datacenter_id=0, worker_id=0),
    SnowflakeGenerator(datacenter_id=0, worker_id=1),
    SnowflakeGenerator(datacenter_id=0, worker_id=2),
])
ids = coord.generate_batch(9)
# Round-robin: worker 0,1,2,0,1,2,0,1,2
assert len(set(ids)) == 9  # all unique

# Batch generation
batch = sf_gen.generate_batch(100)
assert len(set(batch)) == 100  # all unique
assert batch == sorted(batch)  # monotonically increasing

EXAMPLE USAGE WITH ASSERTIONS
------------------------------
# Snowflake IDs are 64-bit positive integers
gen = SnowflakeGenerator(datacenter_id=0, worker_id=0)
id1 = gen.generate()
assert isinstance(id1, int)
assert 0 < id1 < 2**63  # fits in signed 64-bit

# Snowflake IDs are time-sortable
ids = gen.generate_batch(10)
assert ids == sorted(ids)

# Snowflake parse round-trip
gen2 = SnowflakeGenerator(datacenter_id=7, worker_id=12)
id1 = gen2.generate()
parsed = SnowflakeGenerator.parse(id1)
assert parsed["datacenter_id"] == 7
assert parsed["worker_id"] == 12

# Ticket servers produce interleaved sequences
ts1 = TicketServerGenerator(step=3, offset=1)
ts2 = TicketServerGenerator(step=3, offset=2)
ts3 = TicketServerGenerator(step=3, offset=3)
assert ts1.generate() == 1
assert ts2.generate() == 2
assert ts3.generate() == 3
assert ts1.generate() == 4

# ULIDs are 26 characters, lexicographically sortable
ulid_gen = ULIDGenerator()
ids = ulid_gen.generate_batch(5)
assert all(len(id) == 26 for id in ids)
assert ids == sorted(ids)

# All generators produce unique IDs
for GenClass in [UUIDGenerator]:
    gen = GenClass()
    ids = gen.generate_batch(1000)
    assert len(set(ids)) == 1000

CONSTRAINTS
-----------
- Snowflake: 41-bit timestamp supports ~69 years from custom epoch
- Snowflake: 5-bit datacenter_id (0-31), 5-bit worker_id (0-31)
- Snowflake: 12-bit sequence (0-4095 per millisecond per worker)
- Snowflake IDs must be monotonically increasing within a single generator
- Ticket server must be safe for concurrent access (use threading.Lock)
- ULID must use Crockford's Base32 encoding
- No external dependencies beyond Python standard library
- Target: 200-350 lines of code

TESTING REQUIREMENTS
--------------------
Write tests in test_unique_id_generator.py using pytest. Include these test cases:

1.  Snowflake generates unique IDs across 10,000 generations
2.  Snowflake IDs are monotonically increasing
3.  Snowflake parse correctly extracts all fields
4.  Snowflake handles sequence overflow within same millisecond (waits for next ms)
5.  Snowflake detects backward clock and raises error
6.  Snowflake respects datacenter_id and worker_id bit ranges (0-31)
7.  Ticket server with step=2 produces correct interleaved sequences
8.  Ticket server is thread-safe (concurrent generation produces no duplicates)
9.  UUID generates valid format strings
10. ULID is 26 characters in Crockford Base32
11. ULID is lexicographically sortable by time
12. Coordinator distributes across generators round-robin
13. Batch generation produces all unique IDs
14. Flake ID hex strings are time-sortable
15. IDs from different workers in same millisecond are still unique

IMPORTANT - EFFORT LEVEL: MINIMAL
Keep plan VERY brief (2-3 paragraphs max). Focus only on algorithm choice. Skip architectural discussions and detailed analysis.

Plan written to `PLAN.md`. 

**Summary:** Single-file implementation with 5 generators (UUID, Snowflake, TicketServer, FlakeID, ULID) plus a round-robin coordinator, all sharing an `IDGenerator` ABC. Key points:

- **Snowflake**: bit-shift arithmetic, sequence overflow waits for next ms, clock regression raises error, injectable clock for testing
- **TicketServer**: counter with `threading.Lock`, configurable step/offset
- **FlakeID**: 128-bit as zero-padded hex (ensures string sortability)
- **ULID**: Crockford Base32, 48-bit timestamp + 80-bit random
- **All time-based generators** accept `clock_fn` for deterministic tests
- ~300 lines, no external dependencies, 15 test cases in a separate file

Confidence: **HIGH** — the spec is precise and the algorithms are well-established.

[Committed changes to planner branch]