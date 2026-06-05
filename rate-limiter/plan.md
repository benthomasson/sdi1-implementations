# Plan (Iteration 1)

Task: RATE LIMITER
System Design Interview Vol 1 - Chapter 4

OVERVIEW
--------
Implement a rate limiter that supports multiple rate-limiting algorithms as an
HTTP middleware simulation. The rate limiter protects APIs from abuse by
throttling requests that exceed configured limits. It operates as an in-memory
single-process system where each algorithm is a pluggable strategy.

The system must support four algorithms:
  1. Token Bucket - tokens refill at a fixed rate, each request consumes a token
  2. Fixed Window Counter - counts requests in fixed time windows
  3. Sliding Window Log - tracks exact timestamps of each request
  4. Sliding Window Counter - hybrid of fixed window and sliding window log

REQUIREMENTS
------------
1.  Implement a RateLimiter base class (abstract) with method `allow_request(client_id: str) -> bool`.
2.  Implement TokenBucketLimiter with configurable bucket_size and refill_rate (tokens/second).
    - Each client gets their own bucket.
    - Tokens refill continuously based on elapsed time since last request.
    - A request is allowed if at least 1 token is available; it consumes 1 token.
3.  Implement FixedWindowCounterLimiter with configurable max_requests and window_size_seconds.
    - Window boundaries are aligned to wall-clock time (floor division of timestamp by window size).
    - Counter resets at each new window boundary.
4.  Implement SlidingWindowLogLimiter with configurable max_requests and window_size_seconds.
    - Maintains a list of request timestamps per client.
    - On each request, prune timestamps older than window_size_seconds.
    - Allow if count of remaining timestamps < max_requests.
5.  Implement SlidingWindowCounterLimiter with configurable max_requests and window_size_seconds.
    - Uses weighted combination of current and previous window counts.
    - Weight of previous window = 1 - (elapsed time in current window / window_size).
    - Weighted count = prev_count * weight + current_count.
    - Allow if weighted count < max_requests.
6.  Implement an HTTPRateLimitMiddleware class that wraps a rate limiter.
    - Method: handle_request(request: dict) -> dict
    - Request dict has keys: "client_id", "path", "method", "timestamp" (float)
    - Returns response dict with keys: "status_code" (200 or 429), "headers" dict
    - Headers must include "X-RateLimit-Remaining" and "X-RateLimit-Retry-After" (seconds until reset, when throttled)
7.  Support per-path rate limiting rules: different limits for different API endpoints.
8.  All algorithms must accept an optional `current_time` parameter (float) for deterministic testing
    instead of using time.time().
9.  Implement a RateLimiterFactory that creates limiters by algorithm name string.
10. Track metrics: total_allowed, total_denied per client.

DATA MODELS
-----------
class RateLimiter(ABC):
    @abstractmethod
    def allow_request(self, client_id: str, current_time: float = None) -> bool: ...
    def get_remaining(self, client_id: str, current_time: float = None) -> int: ...
    def get_retry_after(self, client_id: str, current_time: float = None) -> float: ...

class TokenBucketLimiter(RateLimiter):
    def __init__(self, bucket_size: int, refill_rate: float): ...
    # Internal state per client: tokens (float), last_refill_time (float)

class FixedWindowCounterLimiter(RateLimiter):
    def __init__(self, max_requests: int, window_size_seconds: float): ...
    # Internal state per client: {window_key: count}

class SlidingWindowLogLimiter(RateLimiter):
    def __init__(self, max_requests: int, window_size_seconds: float): ...
    # Internal state per client: deque of timestamps

class SlidingWindowCounterLimiter(RateLimiter):
    def __init__(self, max_requests: int, window_size_seconds: float): ...
    # Internal state per client: {window_key: count}

class HTTPRateLimitMiddleware:
    def __init__(self, default_limiter: RateLimiter, path_rules: dict = None): ...
    def handle_request(self, request: dict) -> dict: ...

class RateLimiterFactory:
    @staticmethod
    def create(algorithm: str, **kwargs) -> RateLimiter: ...

API SPECIFICATION
-----------------
# Create limiters
limiter = TokenBucketLimiter(bucket_size=10, refill_rate=1.0)
limiter = FixedWindowCounterLimiter(max_requests=100, window_size_seconds=60.0)
limiter = SlidingWindowLogLimiter(max_requests=5, window_size_seconds=1.0)
limiter = SlidingWindowCounterLimiter(max_requests=10, window_size_seconds=60.0)

# Use directly
allowed = limiter.allow_request("client_123", current_time=1000.0)
remaining = limiter.get_remaining("client_123", current_time=1000.0)
retry_after = limiter.get_retry_after("client_123", current_time=1000.0)

# Use as middleware
middleware = HTTPRateLimitMiddleware(
    default_limiter=TokenBucketLimiter(10, 1.0),
    path_rules={
        "/api/search": SlidingWindowLogLimiter(5, 1.0),
        "/api/upload": TokenBucketLimiter(2, 0.1),
    }
)
response = middleware.handle_request({
    "client_id": "user_1",
    "path": "/api/search",
    "method": "GET",
    "timestamp": 1000.0
})
# response == {"status_code": 200, "headers": {"X-RateLimit-Remaining": 4, ...}}

# Factory
limiter = RateLimiterFactory.create("token_bucket", bucket_size=10, refill_rate=1.0)
limiter = RateLimiterFactory.create("sliding_window_log", max_requests=5, window_size_seconds=1.0)

EXAMPLE USAGE WITH ASSERTIONS
------------------------------
# Token bucket: burst then throttle
tb = TokenBucketLimiter(bucket_size=3, refill_rate=1.0)
assert tb.allow_request("c1", current_time=0.0) == True   # 2 tokens left
assert tb.allow_request("c1", current_time=0.0) == True   # 1 token left
assert tb.allow_request("c1", current_time=0.0) == True   # 0 tokens left
assert tb.allow_request("c1", current_time=0.0) == False   # denied
assert tb.allow_request("c1", current_time=1.0) == True   # 1 token refilled

# Fixed window: resets at boundary
fw = FixedWindowCounterLimiter(max_requests=2, window_size_seconds=10.0)
assert fw.allow_request("c1", current_time=0.0) == True
assert fw.allow_request("c1", current_time=5.0) == True
assert fw.allow_request("c1", current_time=9.0) == False   # same window, limit hit
assert fw.allow_request("c1", current_time=10.0) == True   # new window

# Sliding window log: precise tracking
swl = SlidingWindowLogLimiter(max_requests=3, window_size_seconds=10.0)
assert swl.allow_request("c1", current_time=1.0) == True
assert swl.allow_request("c1", current_time=2.0) == True
assert swl.allow_request("c1", current_time=3.0) == True
assert swl.allow_request("c1", current_time=4.0) == False
assert swl.allow_request("c1", current_time=11.5) == True  # t=1.0 expired

# Different clients are independent
assert tb.allow_request("c2", current_time=0.0) == True

CONSTRAINTS
-----------
- All state is in-memory (dicts, deques, etc.)
- Must handle thousands of clients without excessive memory usage
- Sliding window log should prune old entries to prevent unbounded memory growth
- All time-based logic must use the current_time parameter for testability
- No external dependencies beyond Python standard library
- Target: 200-400 lines of code

TESTING REQUIREMENTS
--------------------
Write tests in test_rate_limiter.py using pytest. Include these test cases:

1.  Token bucket allows burst up to bucket_size then denies
2.  Token bucket refills tokens over time at the correct rate
3.  Token bucket never exceeds bucket_size even after long idle period
4.  Fixed window counter resets at window boundaries
5.  Fixed window counter boundary edge case (request at exact boundary)
6.  Sliding window log correctly expires old timestamps
7.  Sliding window log denies when window is full
8.  Sliding window counter weighted calculation is correct
9.  Different clients have independent rate limits
10. HTTPRateLimitMiddleware returns 200 for allowed requests
11. HTTPRateLimitMiddleware returns 429 with Retry-After header for denied requests
12. Per-path rate limiting applies different limits to different endpoints
13. RateLimiterFactory creates correct algorithm instances
14. Metrics tracking counts allowed and denied requests correctly
15. Sliding window log memory is bounded (old entries pruned)

IMPORTANT - EFFORT LEVEL: MINIMAL
Keep plan VERY brief (2-3 paragraphs max). Focus only on algorithm choice. Skip architectural discussions and detailed analysis.

Plan written to `PLAN.md`. 

Summary: Single-file implementation (`rate_limiter.py`) with all four algorithms as subclasses of an abstract `RateLimiter`, plus middleware, factory, and metrics. The spec is detailed enough that there are no real design decisions left — it's a straightforward implementation task. High confidence.

[Committed changes to planner branch]