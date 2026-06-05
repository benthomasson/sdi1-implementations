# Plan Review: Rate Limiter

## Plan Strengths

- All four algorithms are correctly implemented: token bucket with continuous refill, fixed window with aligned boundaries, sliding window log with timestamp pruning, sliding window counter with weighted combination.
- `RateLimiter` ABC provides a clean interface with `allow_request`, `get_remaining`, `get_retry_after`, and metrics tracking.
- Token bucket correctly caps refilled tokens at `bucket_size` — long idle periods don't accumulate unbounded tokens.
- Sliding window log uses `deque` with proper pruning (`popleft` while oldest <= cutoff), bounding memory to at most `max_requests` entries.
- Sliding window counter keeps only current and previous window counts, cleaning up older windows on each request.
- `HTTPRateLimitMiddleware` correctly routes per-path rules and falls back to default limiter.
- `RateLimiterFactory` maps algorithm name strings to constructors cleanly.
- All algorithms accept `current_time` parameter for deterministic testing — `time.time()` is only the fallback.

## Plan Gaps

1. **`time.time()` fallback in all algorithms.** When `current_time=None`, each algorithm calls `time.time()`. While the tests always pass `current_time` explicitly, the fallback exists and would make production use non-deterministic. This is the same pattern as other implementations, but here it's by design (the plan specifies optional `current_time`).

2. **No `import time` actually needed.** The `time` module is imported but only used as fallback for `current_time=None`. Since all tests use explicit timestamps and the simulation is deterministic, the fallback is dead code in practice.

3. **Fixed window counter loses previous window count.** Line 101: `self._counters[client_id] = {wk: count + 1}` replaces the entire dict with just the current window. This is fine for `FixedWindowCounterLimiter` (it only needs the current window), but if someone were to combine it with sliding window behavior, the previous window data is gone.

4. **`get_remaining` for token bucket truncates with `int()`.** A bucket with 0.7 tokens reports `get_remaining=0`, but `allow_request` would still deny since it requires `>= 1.0`. This is correct behavior — remaining accurately reports 0 when less than 1 full token is available.

## Implementation Issues (0 test failures)

The implementation is solid with no test failures. Minor observations:

1. **Sliding window log pruning uses `<=` for cutoff.** `while log and log[0] <= cutoff` means a request at exactly `current_time - window_size` is pruned. This is consistent with how the tests expect it to work (test 6 confirms `t=1.0` expires when `cutoff = 1.5`), but it means the effective window is exclusive on the left boundary.

2. **`get_retry_after` for sliding window counter returns time to next window boundary.** This is a rough estimate — the actual retry time depends on when the previous window's weighted count drops enough, which could be sooner than the boundary. The fixed window limiter has the same approach, which is accurate for that algorithm.
