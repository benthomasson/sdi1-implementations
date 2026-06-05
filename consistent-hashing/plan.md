# Plan (Iteration 1)

Task: CONSISTENT HASHING
System Design Interview Vol 1 - Chapter 5

OVERVIEW
--------
Implement a consistent hashing ring that distributes keys across a set of nodes
with minimal redistribution when nodes are added or removed. The system uses
virtual nodes to achieve better load balancing and supports configurable
replication. This is a single-process in-memory simulation of the distributed
hashing technique used by systems like DynamoDB, Cassandra, and Memcached.

The core insight: when a node is added/removed, only K/N keys need to move on
average (K = total keys, N = total nodes), compared to rehashing where nearly
all keys move.

REQUIREMENTS
------------
1.  Implement a ConsistentHashRing class that maps string keys to nodes on a
    hash ring (0 to 2^32 - 1).
2.  Support adding and removing physical nodes. Each physical node maps to
    `num_virtual_nodes` positions on the ring using hash(f"{node_id}#{i}").
3.  Use a sorted data structure to store virtual node positions for efficient
    O(log n) key lookup via binary search.
4.  Implement key lookup: given a key, find the first virtual node position >= hash(key)
    going clockwise on the ring. Wrap around to the first node if past the maximum.
5.  Support configurable number of virtual nodes per physical node (default 150).
    More virtual nodes = better distribution but more memory.
6.  Implement get_nodes(key, n) to return n distinct physical nodes for replication.
    Walk clockwise from the key's position, skipping virtual nodes that map to
    already-selected physical nodes.
7.  Implement load distribution analysis: given a set of keys, report how many
    keys each physical node owns and compute the standard deviation.
8.  When a node is added, compute which keys would be redistributed (moved from
    their current node to the new node).
9.  When a node is removed, compute which keys would be redistributed (moved from
    the removed node to successor nodes).
10. Support custom hash functions (default: MD5 truncated to 32 bits, or SHA-256
    truncated to 32 bits). The hash function is passed as a parameter.
11. Implement a statistics method that returns: node count, virtual node count,
    ring utilization (how evenly spaced virtual nodes are).

DATA MODELS
-----------
from typing import Callable, Optional

class ConsistentHashRing:
    def __init__(self, num_virtual_nodes: int = 150,
                 hash_fn: Callable[[str], int] = None): ...

    def add_node(self, node_id: str) -> list[str]:
        """Add a physical node. Returns list of keys that would move to this node."""
        ...

    def remove_node(self, node_id: str) -> dict[str, str]:
        """Remove a physical node. Returns {key: new_owner_node} for redistributed keys."""
        ...

    def get_node(self, key: str) -> str:
        """Get the primary node responsible for this key."""
        ...

    def get_nodes(self, key: str, n: int) -> list[str]:
        """Get n distinct physical nodes for replication (clockwise walk)."""
        ...

    def get_distribution(self, keys: list[str]) -> dict[str, int]:
        """Return {node_id: key_count} showing how keys are distributed."""
        ...

    def get_stats(self) -> dict:
        """Return ring statistics."""
        ...

    @property
    def nodes(self) -> list[str]:
        """List of physical node IDs."""
        ...

class HashRingVisualizer:
    """Produces a text-based visualization of the ring showing node positions."""
    @staticmethod
    def visualize(ring: ConsistentHashRing, width: int = 60) -> str: ...

API SPECIFICATION
-----------------
# Create ring
ring = ConsistentHashRing(num_virtual_nodes=150)

# Add nodes
ring.add_node("server-1")
ring.add_node("server-2")
ring.add_node("server-3")

# Look up which node owns a key
node = ring.get_node("user:12345")       # -> "server-2"
node = ring.get_node("session:abc")       # -> "server-1"

# Get replication set (3 distinct physical nodes)
replicas = ring.get_nodes("user:12345", n=3)  # -> ["server-2", "server-3", "server-1"]

# Analyze distribution
keys = [f"key:{i}" for i in range(10000)]
dist = ring.get_distribution(keys)
# dist == {"server-1": 3342, "server-2": 3318, "server-3": 3340}

# Add a new node — minimal redistribution
ring.add_node("server-4")
new_dist = ring.get_distribution(keys)
# Approximately 1/4 of keys moved to server-4

# Remove a node
ring.remove_node("server-2")

# Stats
stats = ring.get_stats()
# {"num_physical_nodes": 3, "num_virtual_nodes": 450, "std_dev": ...}

# Visualize
print(HashRingVisualizer.visualize(ring))

EXAMPLE USAGE WITH ASSERTIONS
------------------------------
ring = ConsistentHashRing(num_virtual_nodes=100)
ring.add_node("A")
ring.add_node("B")
ring.add_node("C")

# Deterministic mapping
node1 = ring.get_node("my-key")
node2 = ring.get_node("my-key")
assert node1 == node2  # same key always maps to same node

# Replication returns distinct physical nodes
replicas = ring.get_nodes("my-key", n=3)
assert len(replicas) == 3
assert len(set(replicas)) == 3  # all distinct

# Cannot request more replicas than physical nodes
replicas = ring.get_nodes("my-key", n=5)
assert len(replicas) == 3  # capped at number of physical nodes

# Distribution should be roughly even with enough virtual nodes
keys = [f"k{i}" for i in range(10000)]
dist = ring.get_distribution(keys)
for node, count in dist.items():
    assert 2500 < count < 4500  # roughly 1/3 each, with tolerance

# Adding a node moves approximately 1/N of keys
before = ring.get_distribution(keys)
ring.add_node("D")
after = ring.get_distribution(keys)
moved = sum(1 for k in keys if ring.get_node(k) == "D" and k not in [])
# Approximately 2500 keys moved to D (1/4 of 10000)
assert 1500 < after.get("D", 0) < 3500

# Removing a node redistributes its keys
ring.remove_node("A")
assert "A" not in ring.nodes
for k in keys:
    assert ring.get_node(k) in ["B", "C", "D"]

CONSTRAINTS
-----------
- Hash ring positions: 0 to 2^32 - 1 (32-bit unsigned integer space)
- Use bisect module for O(log n) position lookups on the sorted ring
- Virtual node positions stored in a sorted list for binary search
- No external dependencies beyond Python standard library
- Support up to 1000 physical nodes with 150 virtual nodes each (150,000 ring positions)
- Key lookup must be O(log V) where V is total virtual nodes
- Target: 150-300 lines of code

TESTING REQUIREMENTS
--------------------
Write tests in test_consistent_hashing.py using pytest. Include these test cases:

1.  Same key always maps to the same node (determinism)
2.  Adding a node causes approximately 1/N of keys to redistribute
3.  Removing a node redistributes only that node's keys to other nodes
4.  Distribution is roughly even with sufficient virtual nodes (std dev check)
5.  More virtual nodes leads to better distribution (compare 10 vs 200 vnodes)
6.  get_nodes returns exactly min(n, num_physical_nodes) distinct nodes
7.  Replication nodes are in clockwise order on the ring
8.  Ring with 1 node assigns all keys to that node
9.  Ring with 0 nodes raises appropriate error on lookup
10. Custom hash function is used correctly
11. Adding then removing same node returns ring to original state
12. Keys that don't move after adding a node still map to same node
13. Visualizer produces non-empty output
14. Stats method returns correct counts

IMPORTANT - EFFORT LEVEL: MINIMAL
Keep plan VERY brief (2-3 paragraphs max). Focus only on algorithm choice. Skip architectural discussions and detailed analysis.

Plan written to `PLAN.md`. 

**Summary:** Single-file implementation using Python's `bisect` module for O(log V) lookups on a sorted list of virtual node positions. The ring tracks keys seen through `get_node`/`get_distribution` calls to support redistribution reporting on `add_node`/`remove_node`. Default hash is MD5 truncated to 32 bits. Confidence is **HIGH** — the algorithm is well-understood and the spec is precise.

[Committed changes to planner branch]