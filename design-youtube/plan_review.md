# Plan Review: Design YouTube

## Plan Strengths

- DAG-based processing pipeline is well-designed: Kahn's algorithm for topological sort, proper cycle detection, stage grouping by execution level, and cascading skip on failure.
- Good separation of concerns: `ProcessingDAG` is generic and reusable, `VideoUploadPipeline` composes it with YouTube-specific handlers.
- HyperLogLog implementation is correct: uses SHA-256 for uniform hashing, leading zeros for rank estimation, small range correction with linear counting.
- Recommendation engine implements three distinct strategies (content/Jaccard, popular, collaborative/co-occurrence) and combines them with configurable weights.
- Streaming manifest quality selection is clean: sort by bitrate descending, return first that fits within bandwidth.

## Plan Gaps

1. **Morris counter is a single counter, not averaged.** A single Morris counter has very high variance. The plan doesn't mention using multiple counters and averaging, which is the standard approach (Morris+) to get reasonable accuracy. With a single counter, the 2x accuracy bound in the test fails ~30% of the time.

2. **No engagement metrics beyond counts.** The plan lists "average watch duration percentage" in requirement 10, but neither the plan nor the implementation tracks watch duration. There's no `record_engagement(video_id, watch_percentage)` or similar.

3. **Video ID collision risk.** `str(uuid.uuid4())[:8]` truncates a UUID to 8 hex chars (32 bits of entropy). With 10,000 videos, collision probability is ~1.2% (birthday problem). The plan specifies "support up to 10,000 videos" but doesn't address this.

4. **`search` includes UPLOADING videos but not PROCESSING.** The search filter is `READY or UPLOADING`, which seems arbitrary — UPLOADING videos aren't watchable either. The plan doesn't specify which statuses should be searchable.

5. **No rate limiting or abuse prevention on view counting.** The same viewer can inflate the exact count by viewing repeatedly. The plan doesn't discuss deduplication or windowed counting.

## Implementation Issues

1. **Morris counter test is flaky.** Fails ~30% of runs because a single Morris counter with X≈12 for n=10000 has standard deviation comparable to the estimate. Fix: use Morris+ (average of k independent counters) or widen the test tolerance.

2. **`random.random()` is unseeded in failure_rate checks and Morris counter.** This makes the pipeline and counter tests non-deterministic. The DAG failure test uses `failure_rate=0.0` (correct), but any test using Morris counter is inherently flaky.

3. **`upload_timestamp` falls back to `time.time()` when `current_time` is None.** This introduces wall-clock dependency into a simulation. All other timestamps in the system use explicit `current_time`; this one breaks the pattern.

4. **`search` does exact tag match, not substring.** Title search uses `query_lower in v.title.lower()` (substring), but tag search uses `query_lower in [t.lower() for t in v.tags]` (exact equality against the list). This means searching for "cat" won't match a tag "cats". The plan says "simple keyword matching" but doesn't specify if tags should substring-match.

5. **`get_feed` content-based strategy only uses first 5 watched videos** (`list(watched)[:5]`). This is an arbitrary cap with no mention in the plan. For users who've watched many videos, this biases recommendations toward whatever happened to be first in the set (which is insertion-ordered but semantically arbitrary).

6. **`recommend_by_content` filters out zero-score candidates** (`if score > 0`). This means videos with no tag overlap are excluded entirely from content recommendations. Correct behavior, but it means content-based recommendations can return fewer than n results even when more videos exist.

7. **ProcessingStage is mutable and reused.** The `status` field on `ProcessingStage` is mutated during `execute()`. If you call `dag.execute()` twice, the second run starts with stages in COMPLETED/FAILED state from the first run. The plan doesn't address re-execution.
