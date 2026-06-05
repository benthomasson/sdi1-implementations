# Plan Review: Key-Value Store

## Plan Strengths

- Correct choice of Dynamo-style architecture: consistent hashing, vector clocks, gossip, Merkle trees, hinted handoff, read repair — all the right building blocks.
- VectorClock implementation is solid: `increment` returns a new clock (immutable), `dominates` and `concurrent_with` logic is correct, `merge` takes max of each counter, `prune` keeps highest entries.
- MerkleTree correctly detects differences between nodes' data sets.
- HintedHandoff is clean and simple — stores hints per target node, delivers on recovery.
- Gossip protocol propagates heartbeat tables between random peers.

## Plan Gaps

1. **Each node independently increments its own vector clock counter on a replicated write.** When the coordinator writes to N=3 nodes, each node calls `local_put(key, value, context)` which calls `context.increment(self.node_id)`. This means node-0 produces `{node-0: 1}`, node-1 produces `{node-1: 1}`, and node-2 produces `{node-2: 1}` — three concurrent vector clocks for what should be a single write. On read, these appear as 3 conflicting versions. The plan doesn't address this fundamental issue.

2. **Hinted handoff counts toward write quorum.** The implementation counts a hinted write as a successful write (`successful_writes += 1`). This means W=2 can be satisfied by 1 real write + 1 hint, weakening the durability guarantee. The plan doesn't discuss whether hints should count.

3. **Gossip failure detection uses `time.time()`.** Like previous implementations, the simulation should use explicit timestamps. Wall-clock time makes gossip tests non-deterministic and the SUSPECT/DOWN transitions untestable.

4. **Anti-entropy compares every pair of nodes.** O(n^2) pair comparison regardless of which nodes share key ranges. The plan mentions Merkle trees but doesn't discuss scoping comparisons to nodes that share responsibility for the same keys (via the consistent hash ring).

5. **No vector clock pruning is actually invoked.** The `prune` method exists on VectorClock but is never called anywhere. The plan mentions "max entries configurable" but the constraint is never enforced.

## Implementation Issues (4 test failures)

1. **Replicated writes create concurrent versions.** `put` writes to N nodes, each incrementing a different counter in the vector clock. On `get`, deduplication by vector clock sees them as distinct concurrent versions. This causes `test_basic_put_and_get`, `test_update_with_context_dominates_old`, and `test_read_quorum_returns_consistent_data` to return 2+ results instead of 1. **Fix:** The coordinator should increment the vector clock once and pass the same clock to all replicas via `local_put_raw`.

2. **`test_write_fails_without_quorum` doesn't raise.** Even with all 3 nodes down, `put` counts hinted handoff writes as successful. With 3 hints for 3 downed nodes, `successful_writes` reaches 3, satisfying W=3. **Fix:** Don't count hinted writes toward the write quorum.

3. **`local_put` always appends the new version.** Lines 125-129: the `dominated_by_existing` check appends the new version regardless of whether it's dominated — the `else` and `if` branches do the same thing. This means a stale write is never rejected.

4. **`time.time()` used in `local_put`, `add_node`, `put` (hinted handoff), and `heartbeat_tick`.** Makes the simulation time-dependent and tests fragile.

5. **`find_differences` falls back to brute-force comparison.** The Merkle tree is built as a proper binary hash tree, but `find_differences` ignores the tree structure entirely — it just compares all keys directly. The tree-based recursive comparison described in the plan is not implemented.

6. **Read repair only pushes `deduped[0]`.** When there are multiple concurrent versions, read repair only propagates the first one, not all concurrent versions. A stale replica should receive all surviving versions.

7. **`_get_preference_list` requests `self.n + len(self.nodes)` nodes for writes** but only `self.n` for reads. The asymmetry is for finding backup nodes for hinted handoff, but if all N preferred nodes are available, the backup list is unused overhead.
