# Plan Review: Unique ID Generator

## Plan Strengths

- All five generators are correctly implemented: UUID v4, Snowflake (64-bit), TicketServer (step/offset), FlakeID (128-bit hex), ULID (Crockford Base32).
- Snowflake bit layout is correct: 1 sign + 41 timestamp + 5 datacenter + 5 worker + 12 sequence. Parse/validate round-trip works.
- Sequence overflow handling is correct: when sequence exceeds 4095, busy-waits for next millisecond.
- Backward clock detection raises `RuntimeError`.
- ULID increments the random part within the same millisecond to ensure monotonicity — correct per the ULID spec.
- All time-based generators accept injectable `clock_fn` for deterministic testing.
- Thread safety with `threading.Lock` on TicketServer, Snowflake, FlakeID, ULID, and Coordinator.
- TicketServer step/offset arithmetic is correct: `counter = offset - step`, first `generate()` returns `offset`.

## Plan Gaps

1. **Snowflake doesn't validate that clock time is after the custom epoch.** If the clock returns a time before the epoch (2024-01-01), the delta is negative and gets masked to 41 bits, producing a wrapped timestamp. `parse()` then returns a wrong `timestamp_ms`. The test `test_snowflake_parse` uses a clock at Nov 2023 (before the epoch), causing the failure.

2. **No `time.time()` fallback concern here.** All generators use `clock_fn or time.time` as default, which is correct — the injectable clock is the primary interface, and the `time.time` default is reasonable for non-test usage.

## Implementation Issues (1 test failure)

1. **`test_snowflake_parse` uses a clock time before the Snowflake epoch.** `make_clock(start_ms=1_700_000_000_123)` is ~Nov 14, 2023, but `DEFAULT_EPOCH_MS` is Jan 1, 2024. The negative delta wraps to a large value. **Fix:** Use a clock time after the epoch, and add a validation check in `generate()` for pre-epoch timestamps.
