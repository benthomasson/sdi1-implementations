# Plan Review: Search Autocomplete

## Plan Strengths

- Trie with per-node top-k caching is correctly implemented: caches are rebuilt bottom-up along the insertion path after every mutation, giving O(prefix_length + k) search.
- Time-weighted decay is applied at read time (in `search_prefix`), keeping the cached raw frequencies accurate without periodic decay sweeps.
- Case insensitivity handled correctly: all queries are lowercased on insert/search.
- Serialization round-trip works: `serialize` exports the tree structure, `deserialize` rebuilds nodes and then reconstructs all caches and size count via `_rebuild_all`.
- Fuzzy search correctly tries single-character edits (substitution, deletion, insertion) on the last character of the prefix.
- `QueryCollector` aggregates duplicate queries before flushing to the trie, using the max timestamp.
- Delete doesn't prune branches (by design) — just clears `is_end` and zeros frequency, which is simple and correct for the use case.

## Plan Gaps

1. **`time.time()` fallback in `insert`, `increment`, and `QueryCollector.record`.** When `timestamp=None`, falls through to `time.time()`. Tests always pass explicit timestamps. Not a bug since the plan specifies optional timestamps, but introduces non-determinism if used without explicit times.

2. **Decay flooring loses precision.** `search_prefix` returns `int(f)` for decayed frequencies, which floors. A query with raw frequency 1 and any decay becomes 0. This could cause queries to disappear from results earlier than expected at low frequencies.

3. **`_update_caches_on_path` walks only the insertion path, not siblings.** When a query is deleted, the cache at each ancestor is rebuilt from children's caches. But children's caches may not contain the next-best query if it was previously evicted from the top-k. This means delete can leave stale caches — a query that should now appear in top-k might be missing until a future insert triggers a cache rebuild on that path. This is a known tradeoff (full cache rebuild would require traversing the entire subtree).

4. **`AutocompleteService.record_query` flushes after every single query.** This defeats the purpose of the `QueryCollector`'s batching — there's no buffering benefit. Either the service should accumulate and flush periodically, or skip the collector entirely.

## Implementation Issues (0 test failures)

The implementation is solid with no test failures. The codebase is clean and well-structured. No correctness bugs found.
