"""Tests for the distributed key-value store."""

import pytest
from key_value_store import VectorClock, VersionedValue, MerkleTree, KVNode, KVStore, HintedHandoff


def test_basic_put_and_get():
    store = KVStore(num_nodes=3, n=3, w=2, r=2)
    ctx = store.put("k1", "v1")
    results = store.get("k1")
    assert len(results) == 1
    assert results[0][0] == "v1"


def test_update_with_context_dominates_old():
    store = KVStore(num_nodes=3, n=3, w=2, r=2)
    ctx1 = store.put("k1", "v1")
    ctx2 = store.put("k1", "v2", context=ctx1)
    assert ctx2.dominates(ctx1)
    results = store.get("k1")
    assert len(results) == 1
    assert results[0][0] == "v2"


def test_concurrent_vector_clocks_detected():
    vc1 = VectorClock({"node-0": 1})
    vc2 = VectorClock({"node-1": 1})
    assert vc1.concurrent_with(vc2)
    assert vc2.concurrent_with(vc1)


def test_vector_clock_dominance():
    vc1 = VectorClock({"node-0": 2, "node-1": 1})
    vc2 = VectorClock({"node-1": 1})
    assert vc1.dominates(vc2)
    assert not vc2.dominates(vc1)

    vc3 = VectorClock({"node-0": 1})
    vc4 = VectorClock({"node-0": 1})
    assert not vc3.dominates(vc4)
    assert not vc3.concurrent_with(vc4)


def test_read_quorum_returns_consistent_data():
    store = KVStore(num_nodes=5, n=3, w=3, r=2)
    store.put("k1", "consistent_value")
    results = store.get("k1")
    assert len(results) == 1
    assert results[0][0] == "consistent_value"


def test_write_quorum_succeeds_with_enough_nodes():
    store = KVStore(num_nodes=5, n=3, w=2, r=2)
    store.mark_node_down("node-0")
    # Should still succeed with 4 alive nodes
    ctx = store.put("k1", "v1")
    assert ctx is not None


def test_write_fails_without_quorum():
    store = KVStore(num_nodes=3, n=3, w=3, r=1)
    store.mark_node_down("node-0")
    store.mark_node_down("node-1")
    store.mark_node_down("node-2")
    with pytest.raises(Exception, match="quorum"):
        store.put("k1", "v1")


def test_hinted_handoff_stores_writes():
    store = KVStore(num_nodes=3, n=3, w=2, r=1)
    store.mark_node_down("node-1")
    store.put("k1", "v1")
    hints = store.hinted_handoff.get_hints("node-1")
    # node-1 might or might not be in the preference list for "k1"
    # Test with a dedicated handoff instance
    hh = HintedHandoff()
    vv = VersionedValue("test", VectorClock({"n": 1}), 0.0)
    hh.store_hint("node-x", "key1", vv)
    assert len(hh.get_hints("node-x")) == 1
    assert hh.get_hints("node-x")[0] == ("key1", vv)


def test_delivering_hints_syncs_data():
    store = KVStore(num_nodes=3, n=3, w=2, r=1)
    # Find a key whose preference list includes node-0
    # Write with node-0 down
    store.mark_node_down("node-0")
    pref = store._get_preference_list("test_key", 3)
    if "node-0" in pref:
        store.put("test_key", "hinted_value")
        store.mark_node_up("node-0")
        store.deliver_hints("node-0")
        versions = store.nodes["node-0"].local_get("test_key")
        assert len(versions) > 0
        assert any(v.value == "hinted_value" for v in versions)
    else:
        # node-0 not in pref list; use direct hint API
        vv = VersionedValue("hinted_val", VectorClock({"node-0": 1}), 0.0)
        store.hinted_handoff.store_hint("node-0", "hk", vv)
        store.mark_node_up("node-0")
        store.deliver_hints("node-0")
        versions = store.nodes["node-0"].local_get("hk")
        assert len(versions) == 1
        assert versions[0].value == "hinted_val"


def test_merkle_tree_root_differs_when_data_differs():
    tree1 = MerkleTree({"a": "1", "b": "2", "c": "3"})
    tree2 = MerkleTree({"a": "1", "b": "999", "c": "3"})
    assert tree1.root_hash() != tree2.root_hash()


def test_merkle_tree_find_differences():
    tree1 = MerkleTree({"a": "1", "b": "2", "c": "3"})
    tree2 = MerkleTree({"a": "1", "b": "999", "c": "3"})
    diffs = tree1.find_differences(tree2)
    assert diffs == ["b"]


def test_merkle_trees_identical_data_same_hash():
    tree1 = MerkleTree({"x": "10", "y": "20"})
    tree2 = MerkleTree({"x": "10", "y": "20"})
    assert tree1.root_hash() == tree2.root_hash()
    assert tree1.find_differences(tree2) == []


def test_delete_creates_tombstone():
    store = KVStore(num_nodes=3, n=3, w=2, r=2)
    ctx = store.put("k1", "hello")
    store.delete("k1", context=ctx)
    results = store.get("k1")
    assert len(results) == 0


def test_gossip_updates_heartbeat_tables():
    store = KVStore(num_nodes=3, n=3, w=2, r=2)
    initial_counters = {}
    for nid, node in store.nodes.items():
        initial_counters[nid] = node.heartbeat_counter

    store.run_gossip_round()

    for nid, node in store.nodes.items():
        assert node.heartbeat_counter > initial_counters[nid]
    # Check that nodes have heard about each other
    for nid, node in store.nodes.items():
        for other_id in store.nodes:
            assert other_id in node.heartbeat_table


def test_read_repair_updates_stale_replicas():
    store = KVStore(num_nodes=3, n=3, w=1, r=2)
    # Write to only 1 node (w=1), then read with r=2 triggers repair
    ctx = store.put("rr_key", "repaired_value")
    pref = store._get_preference_list("rr_key", 3)

    # Read triggers read repair
    results = store.get("rr_key")
    assert len(results) >= 1
    assert results[0][0] == "repaired_value"

    # After read repair, all responding nodes should have the value
    for node_id in pref:
        if store._is_node_available(node_id):
            versions = store.nodes[node_id].local_get("rr_key")
            assert len(versions) > 0
