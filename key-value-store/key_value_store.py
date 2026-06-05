"""Distributed key-value store simulation (Dynamo-style)."""

import hashlib
import random
from dataclasses import dataclass, field


@dataclass
class VectorClock:
    """Logical clock for tracking causality across nodes."""
    counters: dict[str, int] = field(default_factory=dict)

    def increment(self, node_id: str) -> 'VectorClock':
        new_counters = dict(self.counters)
        new_counters[node_id] = new_counters.get(node_id, 0) + 1
        return VectorClock(new_counters)

    def merge(self, other: 'VectorClock') -> 'VectorClock':
        merged = dict(self.counters)
        for k, v in other.counters.items():
            merged[k] = max(merged.get(k, 0), v)
        return VectorClock(merged)

    def dominates(self, other: 'VectorClock') -> bool:
        if not other.counters:
            return bool(self.counters)
        all_keys = set(self.counters) | set(other.counters)
        at_least_one_greater = False
        for k in all_keys:
            mine = self.counters.get(k, 0)
            theirs = other.counters.get(k, 0)
            if mine < theirs:
                return False
            if mine > theirs:
                at_least_one_greater = True
        return at_least_one_greater

    def concurrent_with(self, other: 'VectorClock') -> bool:
        return not self.dominates(other) and not other.dominates(self) and self.counters != other.counters

    def prune(self, max_entries: int = 10) -> 'VectorClock':
        if len(self.counters) <= max_entries:
            return self
        sorted_entries = sorted(self.counters.items(), key=lambda x: x[1], reverse=True)
        return VectorClock(dict(sorted_entries[:max_entries]))


@dataclass
class VersionedValue:
    """A value with its vector clock and metadata."""
    value: object
    vector_clock: VectorClock
    timestamp: float
    is_tombstone: bool = False


class MerkleTree:
    """Hash tree for detecting differences between node data."""

    def __init__(self, data: dict[str, str]):
        self.data = dict(data)
        self.keys = sorted(data.keys())
        self._tree = {}
        self._build()

    def _hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    def _build(self):
        if not self.keys:
            self._tree[(0, 0)] = self._hash("")
            return
        self._build_node(0, len(self.keys), 0)

    def _build_node(self, start: int, end: int, depth: int) -> str:
        key = (depth, start)
        if end - start <= 1:
            if start < len(self.keys):
                k = self.keys[start]
                h = self._hash(f"{k}:{self.data[k]}")
            else:
                h = self._hash("")
            self._tree[key] = h
            return h
        mid = (start + end) // 2
        left_hash = self._build_node(start, mid, depth + 1)
        right_hash = self._build_node(mid, end, depth + 1)
        h = self._hash(left_hash + right_hash)
        self._tree[key] = h
        return h

    def root_hash(self) -> str:
        return self._tree.get((0, 0), self._hash(""))

    def find_differences(self, other: 'MerkleTree') -> list[str]:
        if self.root_hash() == other.root_hash():
            return []
        all_keys = sorted(set(self.data.keys()) | set(other.data.keys()))
        diffs = []
        for k in all_keys:
            v1 = self.data.get(k)
            v2 = other.data.get(k)
            if v1 != v2:
                diffs.append(k)
        return diffs


class KVNode:
    """A single storage node in the distributed system."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.store: dict[str, list[VersionedValue]] = {}
        self.heartbeat_counter = 0
        self.heartbeat_table: dict[str, tuple[int, float]] = {}

    def local_put(self, key: str, value: object, vector_clock: VectorClock,
                  is_tombstone: bool = False, current_time: float = 0.0) -> VectorClock:
        new_vc = vector_clock.increment(self.node_id)
        new_version = VersionedValue(value, new_vc, current_time, is_tombstone)
        existing = self.store.get(key, [])
        survivors = [v for v in existing if not new_vc.dominates(v.vector_clock)]
        if not any(v.vector_clock.dominates(new_vc) for v in survivors):
            survivors.append(new_version)
        self.store[key] = survivors
        return new_vc

    def local_put_raw(self, key: str, versioned_value: VersionedValue):
        """Put a pre-built VersionedValue (used for replication/repair)."""
        existing = self.store.get(key, [])
        vc = versioned_value.vector_clock
        survivors = [v for v in existing if not vc.dominates(v.vector_clock)]
        already_dominated = any(v.vector_clock.dominates(vc) for v in survivors)
        if not already_dominated:
            survivors.append(versioned_value)
        self.store[key] = survivors

    def local_get(self, key: str) -> list[VersionedValue]:
        return list(self.store.get(key, []))

    def get_merkle_tree(self) -> MerkleTree:
        data = {}
        for key, versions in self.store.items():
            # Use hash of all version values for merkle comparison
            content = "|".join(
                f"{v.value}:{v.vector_clock.counters}:{v.is_tombstone}" for v in sorted(versions, key=lambda x: x.timestamp)
            )
            data[key] = content
        return MerkleTree(data)

    def heartbeat_tick(self, current_time: float = 0.0):
        self.heartbeat_counter += 1
        self.heartbeat_table[self.node_id] = (self.heartbeat_counter, current_time)

    def receive_gossip(self, other_table: dict[str, tuple[int, float]]):
        for node_id, (counter, ts) in other_table.items():
            current = self.heartbeat_table.get(node_id)
            if current is None or counter > current[0]:
                self.heartbeat_table[node_id] = (counter, ts)


class HintedHandoff:
    """Stores writes destined for unavailable nodes."""

    def __init__(self):
        self.hints: dict[str, list[tuple[str, VersionedValue]]] = {}

    def store_hint(self, target_node: str, key: str, versioned_value: VersionedValue):
        self.hints.setdefault(target_node, []).append((key, versioned_value))

    def get_hints(self, target_node: str) -> list[tuple[str, VersionedValue]]:
        return list(self.hints.get(target_node, []))

    def clear_hints(self, target_node: str):
        self.hints.pop(target_node, None)


class KVStore:
    """Coordinator for the distributed key-value store."""

    def __init__(self, num_nodes: int = 5, n: int = 3, w: int = 2, r: int = 2,
                 suspect_timeout: float = 5.0, down_timeout: float = 15.0):
        self.n = n
        self.w = w
        self.r = r
        self.suspect_timeout = suspect_timeout
        self.down_timeout = down_timeout
        self.nodes: dict[str, KVNode] = {}
        self.node_status: dict[str, str] = {}  # ALIVE, SUSPECT, DOWN
        self.ring: list[tuple[int, str]] = []
        self.vnodes_per_node = 150
        self.hinted_handoff = HintedHandoff()

        for i in range(num_nodes):
            self.add_node(f"node-{i}")

    def _hash_key(self, key: str) -> int:
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

    def _build_ring(self):
        self.ring = []
        for node_id in self.nodes:
            for i in range(self.vnodes_per_node):
                vnode_key = f"{node_id}:vnode-{i}"
                h = self._hash_key(vnode_key)
                self.ring.append((h, node_id))
        self.ring.sort()

    def _get_preference_list(self, key: str, count: int) -> list[str]:
        """Get the list of distinct nodes responsible for a key."""
        if not self.ring:
            return []
        h = self._hash_key(key)
        n = len(self.ring)
        idx = 0
        for i, (ring_hash, _) in enumerate(self.ring):
            if ring_hash >= h:
                idx = i
                break
        else:
            idx = 0
        result = []
        seen = set()
        for i in range(n):
            _, node_id = self.ring[(idx + i) % n]
            if node_id not in seen:
                seen.add(node_id)
                result.append(node_id)
                if len(result) == count:
                    break
        return result

    def add_node(self, node_id: str, current_time: float = 0.0):
        node = KVNode(node_id)
        self.nodes[node_id] = node
        self.node_status[node_id] = "ALIVE"
        node.heartbeat_tick(current_time)
        for other_id, other_node in self.nodes.items():
            if other_id != node_id:
                node.heartbeat_table[other_id] = (0, current_time)
                other_node.heartbeat_table[node_id] = (0, current_time)
        self._build_ring()

    def remove_node(self, node_id: str):
        self.nodes.pop(node_id, None)
        self.node_status.pop(node_id, None)
        self._build_ring()

    def mark_node_down(self, node_id: str):
        if node_id in self.node_status:
            self.node_status[node_id] = "DOWN"

    def mark_node_up(self, node_id: str):
        if node_id in self.node_status:
            self.node_status[node_id] = "ALIVE"

    def _is_node_available(self, node_id: str) -> bool:
        return self.node_status.get(node_id) == "ALIVE"

    def put(self, key: str, value: object, context: VectorClock = None,
            current_time: float = 0.0) -> VectorClock:
        if context is None:
            context = VectorClock()
        pref_list = self._get_preference_list(key, self.n + len(self.nodes))
        target_nodes = pref_list[:self.n]
        backup_nodes = pref_list[self.n:]

        coordinator = target_nodes[0] if target_nodes else list(self.nodes.keys())[0]
        new_vc = context.increment(coordinator)
        vv = VersionedValue(value, new_vc, current_time)

        successful_writes = 0
        for node_id in target_nodes:
            if self._is_node_available(node_id):
                self.nodes[node_id].local_put_raw(key, vv)
                successful_writes += 1
            else:
                self.hinted_handoff.store_hint(node_id, key, vv)
                for backup_id in backup_nodes:
                    if self._is_node_available(backup_id) and backup_id not in target_nodes:
                        self.nodes[backup_id].local_put_raw(key, vv)
                        break

        if successful_writes < self.w:
            raise Exception(f"Write quorum not met: needed {self.w}, got {successful_writes}")
        return new_vc

    def get(self, key: str) -> list[tuple[object, VectorClock]]:
        pref_list = self._get_preference_list(key, self.n)
        all_versions: list[VersionedValue] = []
        responding_nodes: list[tuple[str, list[VersionedValue]]] = []

        read_count = 0
        for node_id in pref_list:
            if self._is_node_available(node_id):
                versions = self.nodes[node_id].local_get(key)
                responding_nodes.append((node_id, versions))
                all_versions.extend(versions)
                read_count += 1
                if read_count >= self.r:
                    break

        if read_count < self.r:
            raise Exception(f"Read quorum not met: needed {self.r}, got {read_count}")

        # Filter tombstones
        live_versions = [v for v in all_versions if not v.is_tombstone]
        if not live_versions:
            return []

        # Keep only non-dominated versions
        result = []
        for v in live_versions:
            dominated = any(
                other.vector_clock.dominates(v.vector_clock)
                for other in live_versions if other is not v
            )
            if not dominated:
                result.append(v)

        # Deduplicate by vector clock
        seen = []
        deduped = []
        for v in result:
            vc_key = tuple(sorted(v.vector_clock.counters.items()))
            if vc_key not in seen:
                seen.append(vc_key)
                deduped.append(v)

        # Read repair: push all surviving versions to stale replicas
        for version in deduped:
            for node_id, node_versions in responding_nodes:
                node_has_version = any(
                    v.vector_clock.counters == version.vector_clock.counters
                    for v in node_versions
                )
                if not node_has_version:
                    self.nodes[node_id].local_put_raw(key, version)

        return [(v.value, v.vector_clock) for v in deduped]

    def delete(self, key: str, context: VectorClock = None,
               current_time: float = 0.0) -> VectorClock:
        if context is None:
            context = VectorClock()
        pref_list = self._get_preference_list(key, self.n)
        coordinator = pref_list[0] if pref_list else list(self.nodes.keys())[0]
        new_vc = context.increment(coordinator)
        vv = VersionedValue(None, new_vc, current_time, is_tombstone=True)

        successful = 0
        for node_id in pref_list:
            if self._is_node_available(node_id):
                self.nodes[node_id].local_put_raw(key, vv)
                successful += 1
        if successful < self.w:
            raise Exception(f"Delete quorum not met: needed {self.w}, got {successful}")
        return new_vc

    def run_gossip_round(self, current_time: float = 0.0):
        alive_nodes = [nid for nid in self.nodes if self._is_node_available(nid)]
        for node_id in alive_nodes:
            node = self.nodes[node_id]
            node.heartbeat_tick(current_time)
            peers = [n for n in alive_nodes if n != node_id]
            if peers:
                targets = random.sample(peers, min(2, len(peers)))
                for target_id in targets:
                    self.nodes[target_id].receive_gossip(node.heartbeat_table)

        for node_id in self.nodes:
            if self.node_status[node_id] == "DOWN":
                continue
            for other_id, node in self.nodes.items():
                if other_id == node_id:
                    continue
                entry = node.heartbeat_table.get(node_id)
                if entry:
                    _, ts = entry
                    age = current_time - ts
                    if age > self.down_timeout:
                        self.node_status[node_id] = "DOWN"
                    elif age > self.suspect_timeout:
                        if self.node_status[node_id] == "ALIVE":
                            self.node_status[node_id] = "SUSPECT"

    def run_anti_entropy(self):
        node_ids = [nid for nid in self.nodes if self._is_node_available(nid)]
        for i in range(len(node_ids)):
            for j in range(i + 1, len(node_ids)):
                n1 = self.nodes[node_ids[i]]
                n2 = self.nodes[node_ids[j]]
                t1 = n1.get_merkle_tree()
                t2 = n2.get_merkle_tree()
                diffs = t1.find_differences(t2)
                for key in diffs:
                    v1 = n1.local_get(key)
                    v2 = n2.local_get(key)
                    # Sync: give each node versions it doesn't have
                    for v in v1:
                        n2.local_put_raw(key, v)
                    for v in v2:
                        n1.local_put_raw(key, v)

    def deliver_hints(self, node_id: str):
        if not self._is_node_available(node_id):
            return
        hints = self.hinted_handoff.get_hints(node_id)
        node = self.nodes[node_id]
        for key, vv in hints:
            node.local_put_raw(key, vv)
        self.hinted_handoff.clear_hints(node_id)
