# Plan Review: URL Shortener

## Plan Strengths

- Two strategies correctly implemented: counter-based (auto-increment + base62 + zero-pad) and hash-based (SHA-256 + base62 truncation + collision retry).
- Base62 encode/decode is correct and handles edge cases (0 encodes to "0", round-trip preserves all values).
- URL validation uses `urlparse` to check scheme (http/https) and domain (has `.`).
- Custom alias validation: 4-16 chars, alphanumeric only, rejects duplicates.
- Click analytics: click count, per-day histogram (UTC dates), top referrers, recent clicks (capped at 1000 events).
- Expiration correctly checks `now > expires_at` on redirect.
- Rate limiting per creator with sliding 60-second window.
- `current_time` parameter used throughout for deterministic testing — `time.time()` is only the fallback.

## Plan Gaps

1. **Hash-based strategy doesn't deduplicate same URL.** When the same long URL is shortened twice with the hash strategy, it generates the same hash code. But since the first one is already in `self._urls`, the collision handler increments the attempt counter and produces a different code. This means the same URL gets two different short codes — the hash strategy loses its deduplication benefit.

2. **`list_urls` doesn't sort results.** The pagination returns entries in dict insertion order, which is chronological in CPython 3.7+ but not guaranteed semantically. The plan doesn't specify ordering for listings.

3. **Rate limit window cleanup is eager.** `_check_rate_limit` rebuilds the entire timestamp list on every call. For high-volume creators, this is O(n) per shortening request.

## Implementation Issues (0 test failures)

The implementation is solid with no test failures and no correctness bugs. The code is clean and well-structured at 208 lines.
