"""Rate limiter with multiple algorithm strategies and HTTP middleware."""

import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque


class RateLimiter(ABC):
    """Abstract base for rate limiting algorithms."""

    def __init__(self):
        self.total_allowed = defaultdict(int)
        self.total_denied = defaultdict(int)

    @abstractmethod
    def allow_request(self, client_id: str, current_time: float = None) -> bool:
        ...

    def get_remaining(self, client_id: str, current_time: float = None) -> int:
        return 0

    def get_retry_after(self, client_id: str, current_time: float = None) -> float:
        return 0.0

    def _record(self, client_id: str, allowed: bool):
        if allowed:
            self.total_allowed[client_id] += 1
        else:
            self.total_denied[client_id] += 1


class TokenBucketLimiter(RateLimiter):
    """Token bucket algorithm: tokens refill at a fixed rate."""

    def __init__(self, bucket_size: int, refill_rate: float):
        super().__init__()
        self.bucket_size = bucket_size
        self.refill_rate = refill_rate
        self._buckets = {}  # client_id -> [tokens, last_refill_time]

    def _get_bucket(self, client_id, current_time):
        if client_id not in self._buckets:
            self._buckets[client_id] = [float(self.bucket_size), current_time]
            return self._buckets[client_id]
        bucket = self._buckets[client_id]
        elapsed = current_time - bucket[1]
        bucket[0] = min(self.bucket_size, bucket[0] + elapsed * self.refill_rate)
        bucket[1] = current_time
        return bucket

    def allow_request(self, client_id, current_time=None):
        if current_time is None:
            current_time = time.time()
        bucket = self._get_bucket(client_id, current_time)
        if bucket[0] >= 1.0:
            bucket[0] -= 1.0
            self._record(client_id, True)
            return True
        self._record(client_id, False)
        return False

    def get_remaining(self, client_id, current_time=None):
        if current_time is None:
            current_time = time.time()
        if client_id not in self._buckets:
            return self.bucket_size
        bucket = self._get_bucket(client_id, current_time)
        return int(bucket[0])

    def get_retry_after(self, client_id, current_time=None):
        if current_time is None:
            current_time = time.time()
        if client_id not in self._buckets:
            return 0.0
        bucket = self._get_bucket(client_id, current_time)
        if bucket[0] >= 1.0:
            return 0.0
        return (1.0 - bucket[0]) / self.refill_rate


class FixedWindowCounterLimiter(RateLimiter):
    """Fixed window counter: counts requests in aligned time windows."""

    def __init__(self, max_requests: int, window_size_seconds: float):
        super().__init__()
        self.max_requests = max_requests
        self.window_size = window_size_seconds
        self._counters = defaultdict(dict)  # client_id -> {window_key: count}

    def _window_key(self, t):
        return int(t // self.window_size)

    def allow_request(self, client_id, current_time=None):
        if current_time is None:
            current_time = time.time()
        wk = self._window_key(current_time)
        counters = self._counters[client_id]
        count = counters.get(wk, 0)
        if count < self.max_requests:
            # Clear old windows to save memory
            self._counters[client_id] = {wk: count + 1}
            self._record(client_id, True)
            return True
        self._record(client_id, False)
        return False

    def get_remaining(self, client_id, current_time=None):
        if current_time is None:
            current_time = time.time()
        wk = self._window_key(current_time)
        count = self._counters[client_id].get(wk, 0)
        return max(0, self.max_requests - count)

    def get_retry_after(self, client_id, current_time=None):
        if current_time is None:
            current_time = time.time()
        if self.get_remaining(client_id, current_time) > 0:
            return 0.0
        window_start = self._window_key(current_time) * self.window_size
        return window_start + self.window_size - current_time


class SlidingWindowLogLimiter(RateLimiter):
    """Sliding window log: tracks exact timestamps per client."""

    def __init__(self, max_requests: int, window_size_seconds: float):
        super().__init__()
        self.max_requests = max_requests
        self.window_size = window_size_seconds
        self._logs = defaultdict(deque)  # client_id -> deque of timestamps

    def _prune(self, client_id, current_time):
        log = self._logs[client_id]
        cutoff = current_time - self.window_size
        while log and log[0] <= cutoff:
            log.popleft()

    def allow_request(self, client_id, current_time=None):
        if current_time is None:
            current_time = time.time()
        self._prune(client_id, current_time)
        log = self._logs[client_id]
        if len(log) < self.max_requests:
            log.append(current_time)
            self._record(client_id, True)
            return True
        self._record(client_id, False)
        return False

    def get_remaining(self, client_id, current_time=None):
        if current_time is None:
            current_time = time.time()
        self._prune(client_id, current_time)
        return max(0, self.max_requests - len(self._logs[client_id]))

    def get_retry_after(self, client_id, current_time=None):
        if current_time is None:
            current_time = time.time()
        self._prune(client_id, current_time)
        log = self._logs[client_id]
        if len(log) < self.max_requests:
            return 0.0
        # Earliest entry must expire before a new request is allowed
        return log[0] + self.window_size - current_time


class SlidingWindowCounterLimiter(RateLimiter):
    """Sliding window counter: weighted combination of current and previous window."""

    def __init__(self, max_requests: int, window_size_seconds: float):
        super().__init__()
        self.max_requests = max_requests
        self.window_size = window_size_seconds
        self._counters = defaultdict(dict)  # client_id -> {window_key: count}

    def _window_key(self, t):
        return int(t // self.window_size)

    def _weighted_count(self, client_id, current_time):
        wk = self._window_key(current_time)
        counters = self._counters[client_id]
        current_count = counters.get(wk, 0)
        prev_count = counters.get(wk - 1, 0)
        elapsed = current_time - wk * self.window_size
        weight = 1.0 - elapsed / self.window_size
        return prev_count * weight + current_count

    def allow_request(self, client_id, current_time=None):
        if current_time is None:
            current_time = time.time()
        wk = self._window_key(current_time)
        weighted = self._weighted_count(client_id, current_time)
        if weighted < self.max_requests:
            counters = self._counters[client_id]
            counters[wk] = counters.get(wk, 0) + 1
            # Keep only current and previous window
            keys = [k for k in counters if k < wk - 1]
            for k in keys:
                del counters[k]
            self._record(client_id, True)
            return True
        self._record(client_id, False)
        return False

    def get_remaining(self, client_id, current_time=None):
        if current_time is None:
            current_time = time.time()
        weighted = self._weighted_count(client_id, current_time)
        return max(0, int(self.max_requests - weighted))

    def get_retry_after(self, client_id, current_time=None):
        if current_time is None:
            current_time = time.time()
        if self._weighted_count(client_id, current_time) < self.max_requests:
            return 0.0
        wk = self._window_key(current_time)
        window_start = wk * self.window_size
        return window_start + self.window_size - current_time


class HTTPRateLimitMiddleware:
    """HTTP middleware that applies rate limiting to requests."""

    def __init__(self, default_limiter: RateLimiter, path_rules: dict = None):
        self.default_limiter = default_limiter
        self.path_rules = path_rules or {}

    def handle_request(self, request: dict) -> dict:
        client_id = request["client_id"]
        path = request["path"]
        timestamp = request["timestamp"]
        limiter = self.path_rules.get(path, self.default_limiter)
        allowed = limiter.allow_request(client_id, current_time=timestamp)
        remaining = limiter.get_remaining(client_id, current_time=timestamp)
        headers = {"X-RateLimit-Remaining": remaining}
        if allowed:
            return {"status_code": 200, "headers": headers}
        retry_after = limiter.get_retry_after(client_id, current_time=timestamp)
        headers["X-RateLimit-Retry-After"] = retry_after
        return {"status_code": 429, "headers": headers}


class RateLimiterFactory:
    """Factory to create rate limiters by algorithm name."""

    _algorithms = {
        "token_bucket": TokenBucketLimiter,
        "fixed_window_counter": FixedWindowCounterLimiter,
        "sliding_window_log": SlidingWindowLogLimiter,
        "sliding_window_counter": SlidingWindowCounterLimiter,
    }

    @staticmethod
    def create(algorithm: str, **kwargs) -> RateLimiter:
        cls = RateLimiterFactory._algorithms.get(algorithm)
        if cls is None:
            raise ValueError(f"Unknown algorithm: {algorithm}")
        return cls(**kwargs)
