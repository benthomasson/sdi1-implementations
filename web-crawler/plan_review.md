# Plan Review: Web Crawler

## Plan Strengths

- BloomFilter correctly uses double hashing over a `bytearray` with optimal `m` and `k` computed from standard formulas. No false negatives by construction.
- SimHash correctly computes 64-bit fingerprints: word-level tokenization, per-bit weighted voting, MD5 for token hashing. Hamming distance via XOR + popcount.
- RobotsParser uses longest-match precedence for Allow/Disallow conflicts — the correct semantics per the robots.txt spec.
- URLFrontier uses `heapq` with `(priority, seq, url, depth)` tuples. DFS is achieved by negating the sequence number, giving LIFO behavior in the min-heap.
- URL normalization is thorough: lowercases scheme/host, removes trailing slashes, strips fragments, sorts query parameters, handles default ports.
- Crawler uses a simulated clock (`sim_time`) to advance politeness delays without real sleeps.
- Content deduplication via SimHash with configurable Hamming distance threshold.

## Plan Gaps

1. **BloomFilter `add()` calls `might_contain()` to track stats, but undoes the negative check counter.** Line 93: `self._negative_check_count -= 1` after `might_contain` returned False. This stat-tracking logic is convoluted — it tries to distinguish "checked and not found" from "checked during add". The counter can go negative if items are added without prior checks.

2. **`crawl()` uses `time.time()` for `start_time` and `crawl_duration`.** The crawl_duration measures wall-clock time of the crawl loop, which is fine for a simulation (sub-second), but inconsistent with the simulated time used elsewhere.

3. **Politeness advances `sim_time` by `politeness_delay` after every page**, even when changing hosts. This means if you crawl host A then host B, host B waits unnecessarily. The delay should only apply to same-host consecutive requests (which the frontier already handles).

4. **`_is_duplicate_content` does O(n) comparison against all seen hashes.** For large crawls, this becomes slow. A more efficient approach would use locality-sensitive hashing or bucketing by partial hash.

## Implementation Issues (1 test failure fixed)

1. **`test_crawler_max_pages` failed because the link topology was too narrow.** Each page linked to `[page_j for j != i][:3]`, which means page0 links to pages 1-2-3, but pages 1-3 mostly link back to 0-2-3. Only 4 unique pages were reachable. **Fix:** Changed link generation to `[(i+1+j) % 20 for j in range(3)]` so each page links to its next 3 neighbors in a ring, making all 20 pages reachable.
