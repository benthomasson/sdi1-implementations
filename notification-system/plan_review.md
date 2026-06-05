# Plan Review: Notification System

## Plan Strengths

- Clean architecture: `DeliveryChannel` base class, per-channel subclasses, `TemplateRegistry`, `RateLimiter`, and `NotificationService` orchestrator are well-separated.
- Priority queue correctly uses `heapq` with `(priority, timestamp, seq, notification)` tuples — the `seq` tie-breaker prevents heapq comparison failures on equal `(priority, timestamp)`.
- Rate limiter uses a proper sliding window with `deque`, cleaning up expired entries before checking count.
- Template rendering uses regex substitution with explicit missing-variable detection.
- SMS truncation happens inside `SMSChannel.send`, keeping the channel responsible for its own constraints.
- Retry with exponential backoff correctly computes `delay = base * 2^(attempt-1) * jitter` and re-enqueues with a future `deliver_at`.

## Plan Gaps

1. **`current_time or time.time()` falsy bug.** Lines 213 and 261 use `current_time or time.time()`. When `current_time=0.0` is passed, Python treats `0.0` as falsy and falls through to `time.time()`, breaking the simulation. Same pattern found and fixed in previous implementations.

2. **Opt-out sets status to RATE_LIMITED.** When a user has opted out of a channel, the notification status is set to `RATE_LIMITED` (line 221). This is semantically wrong — it conflates user preference with rate limiting. Should have a distinct status or at least not count toward `total_rate_limited` stats.

3. **`_pending_groups` and `_group_window` are dead code.** The plan specifies notification grouping/batching (requirement 9) and the fields exist, but no grouping logic is implemented anywhere. Notifications are never batched.

4. **`_is_quiet_hours` uses `datetime.fromtimestamp` with implicit local timezone.** This makes the quiet hours test depend on the system's timezone. In a simulation with explicit timestamps, the hour should be derived deterministically — e.g., treat timestamps as UTC.

5. **Double rate-limit check — at enqueue and at delivery.** `send()` checks the rate limit and rejects immediately if exceeded. Then `process_queue()` checks again. The enqueue-time check uses the `send()` call's `current_time`, but doesn't record (since not yet delivered). This means if you enqueue 5 notifications at the same `current_time`, all pass the enqueue check, but only the first N pass the delivery check. The enqueue-time rejection is premature — it should only check at delivery time.

6. **`send_batch` doesn't implement grouping.** It just calls `send()` in a loop. The `group_key` field on `Notification` is never used.

## Implementation Issues (0 test failures, but correctness bugs)

1. **`current_time or time.time()` at lines 213 and 261.** Pass `current_time=0.0` and it silently uses wall-clock time. **Fix:** `current_time if current_time is not None else 0.0`.

2. **Quiet hours timezone dependency.** `datetime.fromtimestamp(current_time).hour` uses the system's local timezone. A test that passes in UTC may fail in other timezones. **Fix:** Use `datetime.utcfromtimestamp` or compute hour directly from the timestamp.

3. **`import datetime` inside method body.** `_is_quiet_hours` has a local `import datetime`. Should be at module level.
