"""Unique ID generation system with multiple strategies."""

import uuid
import time
import random
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Callable, Optional

# Snowflake default epoch: 2024-01-01T00:00:00Z
DEFAULT_EPOCH_MS = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

# Crockford Base32 alphabet
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class IDGenerator(ABC):
    """Abstract base for all ID generators."""

    @abstractmethod
    def generate(self) -> int | str: ...

    def generate_batch(self, n: int) -> list[int | str]:
        return [self.generate() for _ in range(n)]


class UUIDGenerator(IDGenerator):
    """Generates standard UUID v4 strings."""

    def generate(self) -> str:
        return str(uuid.uuid4())


class SnowflakeGenerator(IDGenerator):
    """Twitter Snowflake-style 64-bit ID generator.

    Bit layout: 1 sign | 41 timestamp | 5 datacenter | 5 worker | 12 sequence
    """

    def __init__(self, datacenter_id: int, worker_id: int,
                 epoch_ms: int = None, clock_fn: Callable[[], float] = None):
        if not (0 <= datacenter_id <= 31):
            raise ValueError("datacenter_id must be 0-31")
        if not (0 <= worker_id <= 31):
            raise ValueError("worker_id must be 0-31")
        self.datacenter_id = datacenter_id
        self.worker_id = worker_id
        self.epoch_ms = epoch_ms if epoch_ms is not None else DEFAULT_EPOCH_MS
        self.clock_fn = clock_fn or time.time
        self._sequence = 0
        self._last_timestamp_ms = -1
        self._lock = threading.Lock()

    def _current_ms(self) -> int:
        return int(self.clock_fn() * 1000)

    def _wait_next_ms(self, last_ts: int) -> int:
        ts = self._current_ms()
        while ts <= last_ts:
            ts = self._current_ms()
        return ts

    def generate(self) -> int:
        with self._lock:
            ts = self._current_ms()
            if ts < self.epoch_ms:
                raise RuntimeError(
                    f"Clock is before epoch: {ts} < {self.epoch_ms}")
            if ts < self._last_timestamp_ms:
                raise RuntimeError(
                    f"Clock moved backward: {self._last_timestamp_ms} -> {ts}")
            if ts == self._last_timestamp_ms:
                self._sequence += 1
                if self._sequence > 4095:
                    ts = self._wait_next_ms(ts)
                    self._sequence = 0
            else:
                self._sequence = 0
            self._last_timestamp_ms = ts
            delta = ts - self.epoch_ms
            return ((delta & 0x1FFFFFFFFFF) << 22 |
                    (self.datacenter_id & 0x1F) << 17 |
                    (self.worker_id & 0x1F) << 12 |
                    (self._sequence & 0xFFF))

    @staticmethod
    def parse(snowflake_id: int, epoch_ms: int = None) -> dict:
        """Extract components from a Snowflake ID."""
        epoch = epoch_ms if epoch_ms is not None else DEFAULT_EPOCH_MS
        sequence = snowflake_id & 0xFFF
        worker_id = (snowflake_id >> 12) & 0x1F
        datacenter_id = (snowflake_id >> 17) & 0x1F
        timestamp_ms = (snowflake_id >> 22) + epoch
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        return {
            "timestamp_ms": timestamp_ms,
            "datacenter_id": datacenter_id,
            "worker_id": worker_id,
            "sequence": sequence,
            "datetime": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z",
        }

    @staticmethod
    def validate(snowflake_id: int, epoch_ms: int = None) -> bool:
        """Check if ID is a valid 64-bit positive Snowflake ID."""
        if not isinstance(snowflake_id, int) or snowflake_id < 0 or snowflake_id >= 2**63:
            return False
        parsed = SnowflakeGenerator.parse(snowflake_id, epoch_ms)
        return (0 <= parsed["datacenter_id"] <= 31 and
                0 <= parsed["worker_id"] <= 31 and
                0 <= parsed["sequence"] <= 4095)


class TicketServerGenerator(IDGenerator):
    """Auto-increment ticket server with configurable step and offset."""

    def __init__(self, step: int = 1, offset: int = 1):
        self.step = step
        self._counter = offset - step  # so first generate() returns offset
        self._lock = threading.Lock()

    def generate(self) -> int:
        with self._lock:
            self._counter += self.step
            return self._counter


class FlakeIDGenerator(IDGenerator):
    """128-bit IDs as hex strings: 64-bit timestamp + 48-bit worker + 16-bit sequence."""

    def __init__(self, worker_id: int, clock_fn: Callable[[], float] = None):
        self.worker_id = worker_id & 0xFFFFFFFFFFFF  # 48 bits
        self.clock_fn = clock_fn or time.time
        self._sequence = 0
        self._last_timestamp_ms = -1
        self._lock = threading.Lock()

    def _current_ms(self) -> int:
        return int(self.clock_fn() * 1000)

    def generate(self) -> str:
        with self._lock:
            ts = self._current_ms()
            if ts == self._last_timestamp_ms:
                self._sequence += 1
                if self._sequence > 0xFFFF:
                    while ts <= self._last_timestamp_ms:
                        ts = self._current_ms()
                    self._sequence = 0
            else:
                self._sequence = 0
            self._last_timestamp_ms = ts
            value = (ts << 64) | (self.worker_id << 16) | self._sequence
            return f"{value:032x}"


class ULIDGenerator(IDGenerator):
    """ULID: 48-bit timestamp + 80-bit random, Crockford Base32 encoded (26 chars)."""

    def __init__(self, clock_fn: Callable[[], float] = None):
        self.clock_fn = clock_fn or time.time
        self._last_timestamp_ms = -1
        self._last_random = -1
        self._lock = threading.Lock()

    def _current_ms(self) -> int:
        return int(self.clock_fn() * 1000)

    @staticmethod
    def _encode_base32(value: int, length: int) -> str:
        chars = []
        for _ in range(length):
            chars.append(CROCKFORD_ALPHABET[value & 0x1F])
            value >>= 5
        return ''.join(reversed(chars))

    def generate(self) -> str:
        with self._lock:
            ts = self._current_ms()
            if ts == self._last_timestamp_ms:
                # Increment random part to ensure monotonicity within same ms
                self._last_random += 1
                rand_bits = self._last_random
            else:
                rand_bits = random.getrandbits(80)
                self._last_random = rand_bits
            self._last_timestamp_ms = ts
            # Encode: 10 chars for timestamp (48 bits), 16 chars for random (80 bits)
            return self._encode_base32(ts, 10) + self._encode_base32(rand_bits, 16)


class IDGeneratorCoordinator:
    """Distributes ID generation across multiple generators round-robin."""

    def __init__(self, generators: list[IDGenerator]):
        self.generators = generators
        self._index = 0
        self._lock = threading.Lock()

    def generate(self) -> int | str:
        with self._lock:
            gen = self.generators[self._index % len(self.generators)]
            self._index += 1
        return gen.generate()

    def generate_batch(self, n: int) -> list[int | str]:
        return [self.generate() for _ in range(n)]
