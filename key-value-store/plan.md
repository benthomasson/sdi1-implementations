# Plan (Iteration 1)

Task: KEY-VALUE STORE
System Design Interview Vol 1 - Chapter 6

OVERVIEW
--------
Implement a distributed key-value store simulation within a single process.
The system models multiple storage nodes that communicate via in-memory message
passing. It demonstrates the core concepts from Dynamo-style systems: consistent
hashing for partitioning, vector clocks for conflict resolution, gossip protocol
for failure detection, Merkle trees for anti-entropy repair, and tunable
consistency via quorum reads/writes (W, R, N parameters).

Each "node" is a Python object. The "network" is a coordinator that routes
messages between nodes. This simulates the architecture without actual
networking.

REQUIREMENTS
------------
1.  Implement a KVNode class representing a single storage node. Each node stores
    key-value pairs in a dict with associated vector clocks and timestamps.
2.  Implement a KVStore (coordinator) that manages multiple KVNode instances and
    routes client requests using consistent hashing.
3.  Support configurable consistency via N (replication factor), W (write quorum),
    R (read quorum). Default: N=3, W=2, R=2.
    - Strong consistency when W + R > N.
    - Eventual consistency when W + R <= N.
4.  Implement vector clocks for conflict detection:
    - Each write increments the writing node's counter in the vector clock.
    - On read, if multiple versions exist with concurrent vector clocks (neither
      dominates), return all conflicting versions for client resolution.
    - A vector clock A dominates B if all of A's counters >= B's and at least one is >.
5.  Implement a gossip-style failure detector:
    - Each node maintains a heartbeat counter and timestamp for every other node.
    - Periodically (simulated via method call), each node sends its heartbeat table
      to a random subset of other nodes.
    - A node is considered "suspected failed" if its heartbeat hasn't been updated
      within a configurable timeout.
    - Implement phi-accrual style suspicion: track whether a node is ALIVE, SUSPECT,
      or DOWN.
6.  Implement Merkle trees for anti-entropy:
    - Each node builds a Merkle tree over its key-value pairs (hash of sorted key-value pairs).
    - Two nodes can compare Merkle tree roots to detect inconsistencies.
    - If roots differ, recursively compare subtrees to find the specific keys that differ.
    - Implement a sync/repair method that resolves differences between two nodes.
7.  Implement hinted handoff: when a target node is down, write to another node
    with a "hint" that the data should be forwarded when the target recovers.
8.  Implement read repair: when a read detects stale data on some replicas, push
    the latest version to those replicas.
9.  Support put(key, value, context=None) and get(key) operations.
    - put returns a context (vector clock) that can be passed to subsequent puts.
    - get returns (value, context) or list of (value, context) if conflicting.
10. Implement delete as a tombstone (special marker with vector clock, not immediate removal).

DATA MODELS
-----------
from dataclasses import dataclass, field

@dataclass
class VectorClock:
    counters: dict[str, int] = field(default_factory=dict)

    def increment(self, node_id: str) -> 'VectorClock': ...
    def merge(self, other: 'VectorClock') -> 'VectorClock': ...
    def dominates(self, other: 'VectorClock') -> bool: ...
    def concurrent_with(self, other: 'VectorClock') -> bool: ...

@dataclass
class VersionedValue:
    value: any
    vector_clock: VectorClock
    timestamp: float
    is_tombstone: bool = False

class MerkleTree:
    def __init__(self, data: dict[str, str]): ...
    def root_hash(self) -> str: ...
    def find_differences(self, other: 'MerkleTree') -> list[str]: ...

class KVNode:
    def __init__(self, node_id: str): ...
    def local_put(self, key: str, value: any, vector_clock: VectorClock) -> VectorClock: ...
    def local_get(self, key: str) -> list[VersionedValue]: ...
    def get_merkle_tree(self) -> MerkleTree: ...
    def heartbeat_tick(self): ...
    # Gossip state
    heartbeat_counter: int
    heartbeat_table: dict[str, tuple[int, float]]  # {node_id: (counter, timestamp)}

class HintedHandoff:
    """Stores writes destined for unavailable nodes."""
    def store_hint(self, target_node: str, key: str, versioned_value: VersionedValue): ...
    def get_hints(self, target_node: str) -> list[tuple[str, VersionedValue]]: ...
    def clear_hints(self, target_node: str): ...

class KVStore:
    def __init__(self, num_nodes: int = 5, n: int = 3, w: int = 2, r: int = 2): ...
    def put(self, key: str, value: any, context: VectorClock = None) -> VectorClock: ...
    def get(self, key: str) -> list[tuple[any, VectorClock]]: ...
    def delete(self, key: str, context: VectorClock = None) -> VectorClock: ...
    def add_node(self, node_id: str): ...
    def remove_node(self, node_id: str): ...
    def mark_node_down(self, node_id: str): ...
    def mark_node_up(self, node_id: str): ...
    def run_gossip_round(self): ...
    def run_anti_entropy(self): ...
    def deliver_hints(self, node_id: str): ...

API SPECIFICATION
-----------------
# Create store with 5 nodes, replication factor 3, write quorum 2, read quorum 2
store = KVStore(num_nodes=5, n=3, w=2, r=2)

# Put a value
ctx = store.put("user:1", {"name": "Alice", "age": 30})

# Get a value
results = store.get("user:1")
# results == [( {"name": "Alice", "age": 30}, VectorClock({...}) )]

# Update with context (read-modify-write)
value, ctx = results[0]
value["age"] = 31
new_ctx = store.put("user:1", value, context=ctx)

# Delete (tombstone)
store.delete("user:1", context=new_ctx)

# Simulate node failure
store.mark_node_down("node-2")
ctx = store.put("key1", "value1")  # uses hinted handoff for node-2

# Bring node back and deliver hints
store.mark_node_up("node-2")
store.deliver_hints("node-2")

# Run gossip round (failure detection)
store.run_gossip_round()

# Run anti-entropy (Merkle tree sync)
store.run_anti_entropy()

EXAMPLE USAGE WITH ASSERTIONS
------------------------------
# Basic put/get
store = KVStore(num_nodes=3, n=3, w=2, r=2)
ctx = store.put("k1", "v1")
results = store.get("k1")
assert len(results) == 1
assert results[0][0] == "v1"

# Vector clock conflict detection
store2 = KVStore(num_nodes=3, n=3, w=1, r=1)  # weak consistency
ctx1 = store2.put("k1", "v1")
# Simulate concurrent writes to different nodes (conflict scenario)
# by directly writing to individual nodes with concurrent vector clocks
vc1 = VectorClock({"node-0": 1})
vc2 = VectorClock({"node-1": 1})
assert vc1.concurrent_with(vc2) == True
assert vc1.dominates(vc2) == False

# Vector clock dominance
vc3 = VectorClock({"node-0": 2, "node-1": 1})
assert vc3.dominates(vc2) == True
assert vc2.dominates(vc3) == False

# Tombstone delete
store = KVStore(num_nodes=3, n=3, w=2, r=2)
ctx = store.put("k1", "hello")
store.delete("k1", context=ctx)
results = store.get("k1")
assert len(results) == 0 or results[0][0] is None  # deleted

# Merkle tree detects differences
tree1 = MerkleTree({"a": "1", "b": "2", "c": "3"})
tree2 = MerkleTree({"a": "1", "b": "999", "c": "3"})
assert tree1.root_hash() != tree2.root_hash()
diffs = tree1.find_differences(tree2)
assert "b" in diffs

CONSTRAINTS
-----------
- All nodes are in-memory Python objects within a single process
- Message passing between nodes is simulated via direct method calls
- Support 3-10 nodes with thousands of key-value pairs
- Vector clocks should be prunable (max entries configurable) to prevent unbounded growth
- Merkle tree should use SHA-256 for hashing
- No external dependencies beyond Python standard library
- Target: 350-500 lines of code

TESTING REQUIREMENTS
--------------------
Write tests in test_key_value_store.py using pytest. Include these test cases:

1.  Basic put and get returns correct value
2.  Update with context produces a new vector clock that dominates the old one
3.  Concurrent vector clocks are detected correctly
4.  Vector clock dominance is computed correctly
5.  Read with quorum returns consistent data
6.  Write with quorum succeeds when enough nodes are available
7.  Write fails (raises exception) when too few nodes available for quorum
8.  Hinted handoff stores writes for downed nodes
9.  Delivering hints syncs data to recovered nodes
10. Merkle tree root hash differs when data differs
11. Merkle tree find_differences identifies exactly the differing keys
12. Merkle trees with identical data have the same root hash
13. Delete creates a tombstone, subsequent get returns empty/None
14. Gossip round updates heartbeat tables across nodes
15. Read repair updates stale replicas during read

IMPORTANT - EFFORT LEVEL: MINIMAL
Keep plan VERY brief (2-3 paragraphs max). Focus only on algorithm choice. Skip architectural discussions and detailed analysis.

Plan written to `PLAN.md`. 

Summary: Single-file implementation (~400 LOC) following the spec's data models directly. Consistent hashing with virtual nodes for partitioning, vector clocks with standard dominance semantics (keep concurrent siblings), Merkle trees with SHA-256 for anti-entropy, gossip with ALIVE/SUSPECT/DOWN states, hinted handoff on the coordinator, and inline read repair during gets. Build bottom-up: VectorClock → VersionedValue → MerkleTree → KVNode → HintedHandoff → KVStore → tests.

[Committed changes to planner branch]