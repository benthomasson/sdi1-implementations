"""Search autocomplete system using a trie with top-k caching and time-weighted decay."""

from dataclasses import dataclass, field
import time


@dataclass
class TrieNode:
    children: dict[str, 'TrieNode'] = field(default_factory=dict)
    is_end: bool = False
    frequency: int = 0
    last_updated: float = 0.0
    top_k_cache: list[tuple[str, int]] = field(default_factory=list)


class AutocompleteTrie:
    """Trie-based autocomplete with top-k caching per node."""

    def __init__(self, k: int = 10, decay_factor: float = 0.99):
        self.root = TrieNode()
        self.k = k
        self.decay_factor = decay_factor
        self._size = 0

    def _walk(self, query: str) -> tuple[list[TrieNode], TrieNode | None]:
        """Walk the trie for query, return (path including root, final node or None)."""
        path = [self.root]
        node = self.root
        for ch in query:
            if ch not in node.children:
                return path, None
            node = node.children[ch]
            path.append(node)
        return path, node

    def _update_caches_on_path(self, path: list[TrieNode], query: str):
        """Update top-k caches for all nodes on the path after a mutation.

        path[0] is root, path[i] corresponds to query[:i].
        """
        # Update from bottom (leaf) to top (root)
        for i in range(len(path) - 1, -1, -1):
            node = path[i]
            candidates = {}
            # Collect from all children's caches
            for child in node.children.values():
                for q, f in child.top_k_cache:
                    if q not in candidates or f > candidates[q]:
                        candidates[q] = f
            # If this node itself is an end node, add its own query
            # path[i] represents query[:i]
            if node.is_end and node.frequency > 0:
                node_query = query[:i]
                candidates[node_query] = node.frequency
            items = sorted(candidates.items(), key=lambda x: (-x[1], x[0]))
            node.top_k_cache = items[:self.k]

    def insert(self, query: str, frequency: int = 1, timestamp: float = None):
        """Insert a query with given frequency."""
        query = query.lower()[:200]
        if timestamp is None:
            timestamp = time.time()

        node = self.root
        path = [node]
        for ch in query:
            if ch not in node.children:
                node.children[ch] = TrieNode()
            node = node.children[ch]
            path.append(node)

        if not node.is_end:
            self._size += 1
        node.is_end = True
        node.frequency = frequency
        node.last_updated = timestamp
        self._update_caches_on_path(path, query)

    def increment(self, query: str, amount: int = 1, timestamp: float = None):
        """Increase frequency of a query, inserting if it doesn't exist."""
        query = query.lower()[:200]
        if timestamp is None:
            timestamp = time.time()

        node = self.root
        path = [node]
        for ch in query:
            if ch not in node.children:
                node.children[ch] = TrieNode()
            node = node.children[ch]
            path.append(node)

        if not node.is_end:
            self._size += 1
        node.is_end = True
        node.frequency += amount
        node.last_updated = timestamp
        self._update_caches_on_path(path, query)

    def delete(self, query: str) -> bool:
        """Remove a query from the trie. Returns True if it existed."""
        query = query.lower()[:200]
        path, node = self._walk(query)
        if node is None or not node.is_end:
            return False
        node.is_end = False
        node.frequency = 0
        node.last_updated = 0.0
        self._size -= 1
        self._update_caches_on_path(path, query)
        return True

    def get_frequency(self, query: str) -> int:
        """Get the raw frequency of an exact query."""
        query = query.lower()[:200]
        _, node = self._walk(query)
        if node and node.is_end:
            return node.frequency
        return 0

    def search_prefix(self, prefix: str, k: int = 5, current_time: float = None) -> list[tuple[str, int]]:
        """Return top-k completions for prefix, sorted by (decayed) frequency desc then lexicographic."""
        prefix = prefix.lower()
        if not prefix:
            node = self.root
        else:
            _, node = self._walk(prefix)
            if node is None:
                return []

        if current_time is None:
            return node.top_k_cache[:k]

        # Apply decay to cached results
        decayed = []
        for query, raw_freq in node.top_k_cache:
            # Look up the actual node to get last_updated
            _, qnode = self._walk(query)
            if qnode and qnode.is_end:
                hours = (current_time - qnode.last_updated) / 3600.0
                if hours < 0:
                    hours = 0
                decayed_freq = raw_freq * (self.decay_factor ** hours)
                decayed.append((query, decayed_freq))

        decayed.sort(key=lambda x: (-x[1], x[0]))
        # Return as int (floored)
        return [(q, int(f)) for q, f in decayed[:k]]

    def get_all_queries(self) -> list[tuple[str, int]]:
        """Return all stored queries with frequencies."""
        results = []
        self._collect(self.root, [], results)
        return results

    def _collect(self, node: TrieNode, chars: list[str], results: list):
        if node.is_end:
            results.append(("".join(chars), node.frequency))
        for ch in sorted(node.children):
            chars.append(ch)
            self._collect(node.children[ch], chars, results)
            chars.pop()

    def serialize(self) -> dict:
        """Export trie to a dict structure."""
        return {
            "k": self.k,
            "decay_factor": self.decay_factor,
            "root": self._serialize_node(self.root),
        }

    def _serialize_node(self, node: TrieNode) -> dict:
        return {
            "is_end": node.is_end,
            "frequency": node.frequency,
            "last_updated": node.last_updated,
            "children": {ch: self._serialize_node(child) for ch, child in node.children.items()},
        }

    @classmethod
    def deserialize(cls, data: dict) -> 'AutocompleteTrie':
        """Reconstruct trie from serialized dict."""
        trie = cls(k=data["k"], decay_factor=data["decay_factor"])
        trie.root = trie._deserialize_node(data["root"])
        # Rebuild caches and count
        trie._size = 0
        trie._rebuild_all(trie.root, [])
        return trie

    def _deserialize_node(self, data: dict) -> TrieNode:
        node = TrieNode(
            is_end=data["is_end"],
            frequency=data["frequency"],
            last_updated=data["last_updated"],
        )
        for ch, child_data in data["children"].items():
            node.children[ch] = self._deserialize_node(child_data)
        return node

    def _rebuild_all(self, node: TrieNode, chars: list[str]):
        """Rebuild caches and size count after deserialization."""
        if node.is_end:
            self._size += 1
        for ch in node.children:
            chars.append(ch)
            self._rebuild_all(node.children[ch], chars)
            chars.pop()
        # Rebuild cache bottom-up
        candidates = {}
        if node.is_end and node.frequency > 0:
            candidates["".join(chars)] = node.frequency
        for child in node.children.values():
            for q, f in child.top_k_cache:
                if q not in candidates or f > candidates[q]:
                    candidates[q] = f
        items = sorted(candidates.items(), key=lambda x: (-x[1], x[0]))
        node.top_k_cache = items[:self.k]

    @property
    def size(self) -> int:
        return self._size


class QueryCollector:
    """Collects queries and batch-updates the trie."""

    def __init__(self, trie: AutocompleteTrie):
        self.trie = trie
        self._buffer: list[tuple[str, float]] = []

    def record(self, query: str, timestamp: float = None):
        if timestamp is None:
            timestamp = time.time()
        self._buffer.append((query, timestamp))

    def flush(self):
        """Aggregate buffered queries and update trie."""
        aggregated: dict[str, tuple[int, float]] = {}
        for query, ts in self._buffer:
            query_lower = query.lower()
            if query_lower in aggregated:
                count, max_ts = aggregated[query_lower]
                aggregated[query_lower] = (count + 1, max(max_ts, ts))
            else:
                aggregated[query_lower] = (1, ts)
        self._buffer.clear()
        for query, (count, ts) in aggregated.items():
            self.trie.increment(query, amount=count, timestamp=ts)

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)


class AutocompleteService:
    """High-level autocomplete service with blocklist and fuzzy search."""

    def __init__(self, k: int = 5, decay_factor: float = 0.99, blocklist: set[str] | None = None):
        self.trie = AutocompleteTrie(k=max(k, 10), decay_factor=decay_factor)
        self.collector = QueryCollector(self.trie)
        self.blocklist: set[str] = {t.lower() for t in blocklist} if blocklist else set()
        self._default_k = k

    def record_query(self, query: str, timestamp: float = None):
        self.collector.record(query, timestamp)
        self.collector.flush()

    def _filter(self, results: list[tuple[str, int | float]]) -> list[tuple[str, int | float]]:
        if not self.blocklist:
            return results
        return [(q, f) for q, f in results if not any(b in q for b in self.blocklist)]

    def suggest(self, prefix: str, k: int = 5, current_time: float = None) -> list[str]:
        results = self.trie.search_prefix(prefix, k=k + len(self.blocklist) * 2, current_time=current_time)
        filtered = self._filter(results)
        return [q for q, _ in filtered[:k]]

    def suggest_with_scores(self, prefix: str, k: int = 5, current_time: float = None) -> list[tuple[str, float]]:
        results = self.trie.search_prefix(prefix, k=k + len(self.blocklist) * 2, current_time=current_time)
        filtered = self._filter(results)
        return [(q, float(f)) for q, f in filtered[:k]]

    def fuzzy_suggest(self, prefix: str, k: int = 5, current_time: float = None) -> list[str]:
        """If exact prefix has no results, try single-char edits on the last character."""
        results = self.suggest(prefix, k, current_time)
        if results:
            return results

        if not prefix:
            return []

        candidates = set()
        base = prefix[:-1]
        alphabet = "abcdefghijklmnopqrstuvwxyz "

        # Substitution of last char
        for ch in alphabet:
            alt = base + ch
            candidates.add(alt)

        # Deletion of last char
        candidates.add(base)

        # Insertion after last char
        for ch in alphabet:
            candidates.add(prefix + ch)

        all_results = []
        seen = set()
        for alt in candidates:
            for q, f in self.trie.search_prefix(alt, k=k, current_time=current_time):
                if q not in seen:
                    seen.add(q)
                    all_results.append((q, f))

        all_results.sort(key=lambda x: (-x[1], x[0]))
        filtered = self._filter(all_results)
        return [q for q, _ in filtered[:k]]

    def add_to_blocklist(self, term: str):
        self.blocklist.add(term.lower())

    def get_stats(self) -> dict:
        return {
            "total_queries": self.trie.size,
            "buffer_size": self.collector.buffer_size,
            "blocklist_size": len(self.blocklist),
        }
