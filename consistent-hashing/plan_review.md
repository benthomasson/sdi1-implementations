# Plan Review: Consistent Hashing

## Plan Strengths

- Clear algorithm choice: sorted list + `bisect` for O(log V) lookups is the right call for this scale.
- Virtual node naming scheme `{node_id}#{i}` is simple and deterministic.
- MD5 truncated to 32 bits is a reasonable default — fast, well-distributed, no crypto needs here.
- Redistribution tracking via `add_node`/`remove_node` return values is a clean API design.
- The plan correctly identifies that K/N keys move on average, and the tests verify this statistically.

## Plan Gaps

1. **Key tracking is implicit and side-effectful.** The plan says the ring "tracks keys seen through `get_node`/`get_distribution` calls" but doesn't discuss the implications. Every `get_node` call silently adds to `self._keys`, meaning the set grows unboundedly. In a real system this would be a memory leak. The plan should have noted this tradeoff or proposed an alternative (e.g., passing keys explicitly to `add_node`).

2. **Hash collision handling is unaddressed.** Two virtual nodes could hash to the same position. With 150 vnodes per physical node, collisions are unlikely but possible in the 32-bit space. The current implementation silently overwrites the earlier mapping in `_position_to_node` and inserts a duplicate into `_sorted_positions`. The plan should have noted this and either accepted the probability or handled it.

3. **`add_node` is O(K + V log V)** where K is tracked keys and V is virtual nodes. The plan calls it "well-understood" but doesn't discuss the cost of scanning all tracked keys twice (once for old owners, once for new). This is fine for the simulation scope but worth noting.

4. **`remove_node` scans all tracked keys** to find which ones belong to the removed node, then does another pass for new owners. The plan doesn't discuss this cost.

5. **Stats `std_dev` measures gap variance, not load variance.** The plan says "ring utilization (how evenly spaced virtual nodes are)" which is what's implemented, but gap evenness is a proxy for load balance, not a direct measure. A ring could have even gaps but uneven load if virtual nodes from the same physical node cluster together.

## Implementation Issues

1. **Hash collisions corrupt the ring.** If `hash_fn(f"{node_A}#3") == hash_fn(f"{node_B}#7")`, the second `bisect.insort` adds a duplicate position to `_sorted_positions` while `_position_to_node` overwrites the first mapping. On removal of the second node, `_sorted_positions` still has the position but `_position_to_node` no longer maps it. This would cause a `KeyError` on lookup.

2. **`get_node` has a side effect.** Every call adds the key to `self._keys`. This means `get_distribution(keys)` permanently registers all keys for future redistribution tracking, even if the caller just wanted a snapshot. There's no way to query without registering.

3. **`get_nodes` also registers keys.** Same side-effect issue — calling `get_nodes` for replication routing permanently tracks the key.

4. **`remove_node` of a non-existent node returns `{}` silently.** This is arguably fine, but inconsistent with `get_node` which raises `ValueError` for an empty ring. The plan doesn't specify error behavior for invalid removals.

5. **Visualizer accesses private attributes directly** (`ring._sorted_positions`, `ring._position_to_node`, `ring._node_positions`). Minor, but the plan specified it as a separate class — could have been a method on the ring instead.
