"""Tests for consistent hashing ring."""

import math
import pytest
from consistent_hashing import ConsistentHashRing, HashRingVisualizer


def test_deterministic_mapping():
    ring = ConsistentHashRing(num_virtual_nodes=100)
    ring.add_node("A")
    ring.add_node("B")
    ring.add_node("C")
    assert ring.get_node("my-key") == ring.get_node("my-key")


def test_redistribution_on_add():
    ring = ConsistentHashRing(num_virtual_nodes=150)
    ring.add_node("A")
    ring.add_node("B")
    ring.add_node("C")
    keys = [f"k{i}" for i in range(10000)]

    moved = ring.add_node("D", keys=keys)
    # ~1/4 of keys should move
    assert 1500 < len(moved) < 3500


def test_redistribution_on_remove():
    ring = ConsistentHashRing(num_virtual_nodes=150)
    ring.add_node("A")
    ring.add_node("B")
    ring.add_node("C")
    keys = [f"k{i}" for i in range(10000)]

    owned_by_b = [k for k in keys if ring.get_node(k) == "B"]
    result = ring.remove_node("B", keys=keys)
    assert set(result.keys()) == set(owned_by_b)
    for key, new_owner in result.items():
        assert new_owner in ["A", "C"]


def test_even_distribution():
    ring = ConsistentHashRing(num_virtual_nodes=150)
    ring.add_node("A")
    ring.add_node("B")
    ring.add_node("C")
    keys = [f"k{i}" for i in range(10000)]
    dist = ring.get_distribution(keys)
    for count in dist.values():
        assert 2500 < count < 4500


def test_more_vnodes_better_distribution():
    keys = [f"k{i}" for i in range(10000)]

    ring_few = ConsistentHashRing(num_virtual_nodes=10)
    ring_many = ConsistentHashRing(num_virtual_nodes=200)
    for r in [ring_few, ring_many]:
        r.add_node("A")
        r.add_node("B")
        r.add_node("C")

    dist_few = ring_few.get_distribution(keys)
    dist_many = ring_many.get_distribution(keys)

    def std_dev(d):
        vals = list(d.values())
        mean = sum(vals) / len(vals)
        return math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))

    assert std_dev(dist_many) < std_dev(dist_few)


def test_get_nodes_distinct():
    ring = ConsistentHashRing(num_virtual_nodes=100)
    ring.add_node("A")
    ring.add_node("B")
    ring.add_node("C")
    replicas = ring.get_nodes("my-key", n=3)
    assert len(replicas) == 3
    assert len(set(replicas)) == 3


def test_get_nodes_capped():
    ring = ConsistentHashRing(num_virtual_nodes=100)
    ring.add_node("A")
    ring.add_node("B")
    ring.add_node("C")
    replicas = ring.get_nodes("my-key", n=5)
    assert len(replicas) == 3


def test_single_node():
    ring = ConsistentHashRing(num_virtual_nodes=50)
    ring.add_node("only")
    keys = [f"k{i}" for i in range(100)]
    for k in keys:
        assert ring.get_node(k) == "only"


def test_empty_ring_raises():
    ring = ConsistentHashRing()
    with pytest.raises(ValueError):
        ring.get_node("key")


def test_custom_hash_function():
    import hashlib

    def sha256_hash(key: str) -> int:
        return int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "big")

    ring = ConsistentHashRing(num_virtual_nodes=100, hash_fn=sha256_hash)
    ring.add_node("A")
    ring.add_node("B")
    assert ring.get_node("test") == ring.get_node("test")

    # Verify it uses the custom hash (different from default)
    ring_default = ConsistentHashRing(num_virtual_nodes=100)
    ring_default.add_node("A")
    ring_default.add_node("B")
    # Positions should differ, so at least some keys map differently
    diffs = sum(1 for i in range(1000)
                if ring.get_node(f"k{i}") != ring_default.get_node(f"k{i}"))
    assert diffs > 0


def test_add_remove_roundtrip():
    ring = ConsistentHashRing(num_virtual_nodes=100)
    ring.add_node("A")
    ring.add_node("B")
    keys = [f"k{i}" for i in range(500)]
    before = {k: ring.get_node(k) for k in keys}

    ring.add_node("C")
    ring.remove_node("C")

    after = {k: ring.get_node(k) for k in keys}
    assert before == after


def test_keys_not_moved_stay():
    ring = ConsistentHashRing(num_virtual_nodes=100)
    ring.add_node("A")
    ring.add_node("B")
    keys = [f"k{i}" for i in range(1000)]
    before = {k: ring.get_node(k) for k in keys}

    moved = set(ring.add_node("C", keys=keys))
    for k in keys:
        if k not in moved:
            assert ring.get_node(k) == before[k]


def test_visualizer():
    ring = ConsistentHashRing(num_virtual_nodes=50)
    ring.add_node("server-1")
    ring.add_node("server-2")
    output = HashRingVisualizer.visualize(ring)
    assert len(output) > 0
    assert "server-1" in output
    assert "server-2" in output


def test_stats():
    ring = ConsistentHashRing(num_virtual_nodes=100)
    ring.add_node("A")
    ring.add_node("B")
    ring.add_node("C")
    stats = ring.get_stats()
    assert stats["num_physical_nodes"] == 3
    assert stats["num_virtual_nodes"] == 300
    assert "load_std_dev" in stats
    assert stats["load_std_dev"] > 0


def test_replication_clockwise_order():
    """Replication nodes should be in clockwise order on the ring."""
    ring = ConsistentHashRing(num_virtual_nodes=100)
    ring.add_node("A")
    ring.add_node("B")
    ring.add_node("C")
    replicas = ring.get_nodes("test-key", n=3)
    # First replica should be same as get_node
    assert replicas[0] == ring.get_node("test-key")


def test_hash_collision_skipped():
    """Virtual nodes with colliding positions are skipped, not overwritten."""
    collision_pos = 42

    call_count = [0]
    def colliding_hash(key: str) -> int:
        call_count[0] += 1
        if call_count[0] <= 3:
            return collision_pos
        return hash(key) % (2**32)

    ring = ConsistentHashRing(num_virtual_nodes=3, hash_fn=colliding_hash)
    ring.add_node("A")
    # A gets position 42 on first vnode, then two more at 42 (skipped)
    assert len(ring._node_positions["A"]) == 1

    # Reset and add B — its first vnode also collides at 42, should be skipped
    call_count[0] = 0
    ring.add_node("B")
    assert collision_pos not in ring._node_positions["B"]

    # Removing B should not corrupt A's position
    ring.remove_node("B")
    assert ring.get_node("test") == "A"
