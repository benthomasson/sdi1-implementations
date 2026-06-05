"""Consistent hashing ring with virtual nodes."""

import bisect
import hashlib
import math
from typing import Callable


def default_hash(key: str) -> int:
    """MD5 truncated to 32 bits."""
    return int.from_bytes(hashlib.md5(key.encode()).digest()[:4], "big")


class ConsistentHashRing:
    """Maps string keys to nodes on a hash ring (0 to 2^32-1) using virtual nodes."""

    def __init__(self, num_virtual_nodes: int = 150, hash_fn: Callable[[str], int] = None):
        self.num_virtual_nodes = num_virtual_nodes
        self.hash_fn = hash_fn or default_hash
        self._sorted_positions: list[int] = []
        self._position_to_node: dict[int, str] = {}
        self._node_positions: dict[str, list[int]] = {}
        self._keys: set[str] = set()

    @property
    def nodes(self) -> list[str]:
        """List of physical node IDs."""
        return list(self._node_positions.keys())

    def _get_position(self, key: str) -> int:
        """Find the ring position (index into sorted_positions) for a key hash."""
        h = self.hash_fn(key)
        idx = bisect.bisect_left(self._sorted_positions, h)
        if idx == len(self._sorted_positions):
            idx = 0
        return idx

    def add_node(self, node_id: str) -> list[str]:
        """Add a physical node. Returns list of keys that would move to this node."""
        if node_id in self._node_positions:
            return []

        # Record old owners for tracked keys
        old_owners = {}
        for key in self._keys:
            old_owners[key] = self.get_node(key) if self._sorted_positions else None

        # Add virtual nodes
        positions = []
        for i in range(self.num_virtual_nodes):
            pos = self.hash_fn(f"{node_id}#{i}")
            positions.append(pos)
            self._position_to_node[pos] = node_id
            bisect.insort(self._sorted_positions, pos)
        self._node_positions[node_id] = positions

        # Find keys that moved to the new node
        moved = []
        for key in self._keys:
            new_owner = self.get_node(key)
            if new_owner == node_id and old_owners.get(key) != node_id:
                moved.append(key)
        return moved

    def remove_node(self, node_id: str) -> dict[str, str]:
        """Remove a physical node. Returns {key: new_owner_node} for redistributed keys."""
        if node_id not in self._node_positions:
            return {}

        # Find keys owned by this node before removal
        affected_keys = [k for k in self._keys if self.get_node(k) == node_id]

        # Remove virtual nodes
        for pos in self._node_positions[node_id]:
            del self._position_to_node[pos]
            idx = bisect.bisect_left(self._sorted_positions, pos)
            self._sorted_positions.pop(idx)
        del self._node_positions[node_id]

        # Map affected keys to new owners
        result = {}
        for key in affected_keys:
            if self._sorted_positions:
                result[key] = self.get_node(key)
        return result

    def get_node(self, key: str) -> str:
        """Get the primary node responsible for this key."""
        if not self._sorted_positions:
            raise ValueError("No nodes in the ring")
        self._keys.add(key)
        idx = self._get_position(key)
        return self._position_to_node[self._sorted_positions[idx]]

    def get_nodes(self, key: str, n: int) -> list[str]:
        """Get n distinct physical nodes for replication (clockwise walk)."""
        if not self._sorted_positions:
            raise ValueError("No nodes in the ring")
        self._keys.add(key)
        n = min(n, len(self._node_positions))
        result = []
        seen = set()
        idx = self._get_position(key)
        total = len(self._sorted_positions)
        for i in range(total):
            pos = self._sorted_positions[(idx + i) % total]
            node = self._position_to_node[pos]
            if node not in seen:
                seen.add(node)
                result.append(node)
                if len(result) == n:
                    break
        return result

    def get_distribution(self, keys: list[str]) -> dict[str, int]:
        """Return {node_id: key_count} showing how keys are distributed."""
        dist: dict[str, int] = {node: 0 for node in self._node_positions}
        for key in keys:
            node = self.get_node(key)
            dist[node] = dist.get(node, 0) + 1
        return dist

    def get_stats(self) -> dict:
        """Return ring statistics."""
        positions = self._sorted_positions
        num_vnodes = len(positions)
        num_pnodes = len(self._node_positions)

        if num_vnodes < 2:
            std_dev = 0.0
        else:
            # Compute gaps between consecutive virtual nodes
            gaps = []
            for i in range(num_vnodes):
                gap = (positions[(i + 1) % num_vnodes] - positions[i]) % (2**32)
                gaps.append(gap)
            mean_gap = sum(gaps) / len(gaps)
            variance = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
            std_dev = math.sqrt(variance)

        return {
            "num_physical_nodes": num_pnodes,
            "num_virtual_nodes": num_vnodes,
            "std_dev": std_dev,
        }


class HashRingVisualizer:
    """Produces a text-based visualization of the ring showing node positions."""

    @staticmethod
    def visualize(ring: ConsistentHashRing, width: int = 60) -> str:
        if not ring._sorted_positions:
            return "(empty ring)"

        max_pos = 2**32
        lines = []
        # Show each physical node and its virtual node count
        lines.append(f"Ring: {len(ring._node_positions)} nodes, "
                      f"{len(ring._sorted_positions)} virtual nodes")
        lines.append("-" * width)

        # Simple bar showing position density per node
        segments = width
        segment_owners: list[str] = []
        for i in range(segments):
            pos = int((i / segments) * max_pos)
            idx = bisect.bisect_left(ring._sorted_positions, pos)
            if idx == len(ring._sorted_positions):
                idx = 0
            owner = ring._position_to_node[ring._sorted_positions[idx]]
            segment_owners.append(owner)

        # Assign single-char labels to nodes
        node_list = sorted(ring._node_positions.keys())
        labels = {}
        for i, node in enumerate(node_list):
            labels[node] = chr(ord("A") + i) if i < 26 else str(i)

        bar = "".join(labels.get(o, "?") for o in segment_owners)
        lines.append(f"[{bar}]")
        lines.append("-" * width)

        # Legend
        for node in node_list:
            lines.append(f"  {labels[node]} = {node} "
                          f"({len(ring._node_positions[node])} vnodes)")

        return "\n".join(lines)
