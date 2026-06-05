"""Tests for rate limiter implementations."""

import pytest
from rate_limiter import (
    TokenBucketLimiter,
    FixedWindowCounterLimiter,
    SlidingWindowLogLimiter,
    SlidingWindowCounterLimiter,
    HTTPRateLimitMiddleware,
    RateLimiterFactory,
)


# 1. Token bucket allows burst up to bucket_size then denies
def test_token_bucket_burst_then_deny():
    tb = TokenBucketLimiter(bucket_size=3, refill_rate=1.0)
    assert tb.allow_request("c1", current_time=0.0) is True
    assert tb.allow_request("c1", current_time=0.0) is True
    assert tb.allow_request("c1", current_time=0.0) is True
    assert tb.allow_request("c1", current_time=0.0) is False


# 2. Token bucket refills tokens over time at the correct rate
def test_token_bucket_refill():
    tb = TokenBucketLimiter(bucket_size=3, refill_rate=1.0)
    for _ in range(3):
        tb.allow_request("c1", current_time=0.0)
    assert tb.allow_request("c1", current_time=0.0) is False
    assert tb.allow_request("c1", current_time=1.0) is True  # 1 token refilled
    assert tb.allow_request("c1", current_time=1.0) is False
    assert tb.allow_request("c1", current_time=3.0) is True  # 2 tokens refilled
    assert tb.allow_request("c1", current_time=3.0) is True


# 3. Token bucket never exceeds bucket_size even after long idle
def test_token_bucket_max_cap():
    tb = TokenBucketLimiter(bucket_size=5, refill_rate=1.0)
    tb.allow_request("c1", current_time=0.0)  # 4 tokens
    # After 1000 seconds, should still cap at 5
    assert tb.get_remaining("c1", current_time=1000.0) == 5
    # Use all 5
    for _ in range(5):
        assert tb.allow_request("c1", current_time=1000.0) is True
    assert tb.allow_request("c1", current_time=1000.0) is False


# 4. Fixed window counter resets at window boundaries
def test_fixed_window_resets():
    fw = FixedWindowCounterLimiter(max_requests=2, window_size_seconds=10.0)
    assert fw.allow_request("c1", current_time=0.0) is True
    assert fw.allow_request("c1", current_time=5.0) is True
    assert fw.allow_request("c1", current_time=9.0) is False  # same window
    assert fw.allow_request("c1", current_time=10.0) is True  # new window


# 5. Fixed window counter boundary edge case
def test_fixed_window_exact_boundary():
    fw = FixedWindowCounterLimiter(max_requests=1, window_size_seconds=5.0)
    assert fw.allow_request("c1", current_time=0.0) is True
    assert fw.allow_request("c1", current_time=4.999) is False
    assert fw.allow_request("c1", current_time=5.0) is True  # exact boundary = new window
    assert fw.allow_request("c1", current_time=5.0) is False


# 6. Sliding window log correctly expires old timestamps
def test_sliding_window_log_expiry():
    swl = SlidingWindowLogLimiter(max_requests=3, window_size_seconds=10.0)
    assert swl.allow_request("c1", current_time=1.0) is True
    assert swl.allow_request("c1", current_time=2.0) is True
    assert swl.allow_request("c1", current_time=3.0) is True
    assert swl.allow_request("c1", current_time=4.0) is False
    # t=1.0 expires at t=11.0 (cutoff = 11.5 - 10 = 1.5, so 1.0 <= 1.5 is pruned)
    assert swl.allow_request("c1", current_time=11.5) is True


# 7. Sliding window log denies when window is full
def test_sliding_window_log_full():
    swl = SlidingWindowLogLimiter(max_requests=2, window_size_seconds=5.0)
    assert swl.allow_request("c1", current_time=1.0) is True
    assert swl.allow_request("c1", current_time=2.0) is True
    assert swl.allow_request("c1", current_time=3.0) is False
    assert swl.allow_request("c1", current_time=4.0) is False


# 8. Sliding window counter weighted calculation
def test_sliding_window_counter_weighted():
    swc = SlidingWindowCounterLimiter(max_requests=10, window_size_seconds=60.0)
    # Fill previous window (window 0: t=0..59) with 9 requests
    for i in range(9):
        swc.allow_request("c1", current_time=float(i))
    # At t=75, we're 15s into window 1. Weight of prev = 1 - 15/60 = 0.75
    # prev_count=9, weighted = 9*0.75 = 6.75 + current_count
    # Check: weighted before = 6.75+0 < 10 -> allow (current becomes 1)
    assert swc.allow_request("c1", current_time=75.0) is True
    # weighted before = 6.75+1 = 7.75 < 10 -> allow (current becomes 2)
    assert swc.allow_request("c1", current_time=75.0) is True
    # weighted before = 6.75+2 = 8.75 < 10 -> allow (current becomes 3)
    assert swc.allow_request("c1", current_time=75.0) is True
    # weighted before = 6.75+3 = 9.75 < 10 -> allow (current becomes 4)
    assert swc.allow_request("c1", current_time=75.0) is True
    # weighted before = 6.75+4 = 10.75 >= 10 -> denied
    assert swc.allow_request("c1", current_time=75.0) is False


# 9. Different clients have independent rate limits
def test_independent_clients():
    tb = TokenBucketLimiter(bucket_size=2, refill_rate=1.0)
    assert tb.allow_request("c1", current_time=0.0) is True
    assert tb.allow_request("c1", current_time=0.0) is True
    assert tb.allow_request("c1", current_time=0.0) is False
    # c2 is unaffected
    assert tb.allow_request("c2", current_time=0.0) is True
    assert tb.allow_request("c2", current_time=0.0) is True
    assert tb.allow_request("c2", current_time=0.0) is False


# 10. Middleware returns 200 for allowed requests
def test_middleware_200():
    limiter = TokenBucketLimiter(bucket_size=5, refill_rate=1.0)
    mw = HTTPRateLimitMiddleware(default_limiter=limiter)
    resp = mw.handle_request({
        "client_id": "u1", "path": "/api/data", "method": "GET", "timestamp": 0.0
    })
    assert resp["status_code"] == 200
    assert "X-RateLimit-Remaining" in resp["headers"]


# 11. Middleware returns 429 with Retry-After for denied requests
def test_middleware_429():
    limiter = TokenBucketLimiter(bucket_size=1, refill_rate=1.0)
    mw = HTTPRateLimitMiddleware(default_limiter=limiter)
    mw.handle_request({
        "client_id": "u1", "path": "/api/data", "method": "GET", "timestamp": 0.0
    })
    resp = mw.handle_request({
        "client_id": "u1", "path": "/api/data", "method": "GET", "timestamp": 0.0
    })
    assert resp["status_code"] == 429
    assert "X-RateLimit-Retry-After" in resp["headers"]
    assert resp["headers"]["X-RateLimit-Retry-After"] > 0


# 12. Per-path rate limiting
def test_per_path_limiting():
    default = TokenBucketLimiter(bucket_size=10, refill_rate=1.0)
    search_limiter = TokenBucketLimiter(bucket_size=2, refill_rate=0.5)
    mw = HTTPRateLimitMiddleware(default_limiter=default, path_rules={
        "/api/search": search_limiter,
    })
    # /api/search has limit of 2
    req = lambda path, t: {"client_id": "u1", "path": path, "method": "GET", "timestamp": t}
    assert mw.handle_request(req("/api/search", 0.0))["status_code"] == 200
    assert mw.handle_request(req("/api/search", 0.0))["status_code"] == 200
    assert mw.handle_request(req("/api/search", 0.0))["status_code"] == 429
    # Default path still works
    assert mw.handle_request(req("/api/other", 0.0))["status_code"] == 200


# 13. Factory creates correct instances
def test_factory():
    tb = RateLimiterFactory.create("token_bucket", bucket_size=10, refill_rate=1.0)
    assert isinstance(tb, TokenBucketLimiter)
    fw = RateLimiterFactory.create("fixed_window_counter", max_requests=5, window_size_seconds=10.0)
    assert isinstance(fw, FixedWindowCounterLimiter)
    swl = RateLimiterFactory.create("sliding_window_log", max_requests=5, window_size_seconds=1.0)
    assert isinstance(swl, SlidingWindowLogLimiter)
    swc = RateLimiterFactory.create("sliding_window_counter", max_requests=10, window_size_seconds=60.0)
    assert isinstance(swc, SlidingWindowCounterLimiter)
    with pytest.raises(ValueError):
        RateLimiterFactory.create("unknown")


# 14. Metrics tracking
def test_metrics():
    tb = TokenBucketLimiter(bucket_size=2, refill_rate=1.0)
    tb.allow_request("c1", current_time=0.0)  # allowed
    tb.allow_request("c1", current_time=0.0)  # allowed
    tb.allow_request("c1", current_time=0.0)  # denied
    tb.allow_request("c1", current_time=0.0)  # denied
    assert tb.total_allowed["c1"] == 2
    assert tb.total_denied["c1"] == 2
    # c2 has separate metrics
    tb.allow_request("c2", current_time=0.0)
    assert tb.total_allowed["c2"] == 1
    assert tb.total_denied["c2"] == 0


# 15. Sliding window log memory is bounded
def test_sliding_window_log_memory_bounded():
    swl = SlidingWindowLogLimiter(max_requests=100, window_size_seconds=10.0)
    # Add many requests over time
    for i in range(1000):
        swl.allow_request("c1", current_time=float(i))
    # After t=999, only entries from t=990..999 should remain (cutoff = 989)
    log = swl._logs["c1"]
    assert len(log) <= 100  # bounded by max_requests (at most 10 in window)
    assert all(ts > 989.0 for ts in log)
