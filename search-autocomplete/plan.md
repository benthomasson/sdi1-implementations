# Plan (Iteration 1)

Task: SEARCH AUTOCOMPLETE
System Design Interview Vol 1 - Chapter 13

OVERVIEW
--------
Implement a search autocomplete (typeahead) system as a single-process Python
application. The core data structure is a trie (prefix tree) that stores search
queries with their frequencies. Given a prefix, the system returns the top-k
most popular completions. The system supports incremental updates (new queries
increase frequency), time-weighted decay (recent queries count more), and
efficient prefix matching.

REQUIREMENTS
------------
1.  Implement a TrieNode class as the building block of the trie:
    - Each node stores a character, a dict of children nodes, a flag indicating
      whether it marks the end of a complete word/phrase, and aggregate data
      for optimization (e.g., top-k cache at each node).
2.  Implement an AutocompleteTrie class:
    - insert(query: str, frequency: int = 1): insert a query with initial frequency.
    - search_prefix(prefix: str, k: int = 5) -> list[tuple[str, int]]: return
      top-k completions by frequency, as (query, frequency) pairs.
    - increment(query: str, amount: int = 1): increase frequency of existing query
      or insert it.
    - delete(query: str): remove a query from the trie.
    - get_frequency(query: str) -> int: get frequency of an exact query.
3.  Implement top-k optimization: each trie node caches the top-k completions
    in its subtree. This avoids full subtree traversal on every query.
    - Cache is updated on insert/increment.
    - Configurable k (default 10).
4.  Implement frequency-based ranking: completions are sorted by frequency
    descending, with lexicographic ordering as tiebreaker.
5.  Implement time-weighted frequency decay:
    - Each query entry has a timestamp of last update.
    - Decayed frequency = raw_frequency * decay_factor^(hours_since_last_update).
    - decay_factor is configurable (default 0.99, meaning 1% decay per hour).
    - top-k results use decayed frequencies for ranking.
6.  Implement incremental prefix matching that returns results as the user types
    each character, simulating real-time typeahead behavior.
7.  Implement a QueryCollector that records search queries and periodically
    updates the trie:
    - record(query: str, timestamp: float): log a search query.
    - flush(): batch-update the trie with all collected queries since last flush.
    - Aggregates duplicate queries in the buffer before flushing.
8.  Implement trie serialization: export the trie to a dict structure and
    reconstruct from it. This simulates persistence.
9.  Implement phrase support: queries can be multi-word phrases like
    "new york pizza". Matching is by prefix of the full phrase.
10. Implement filtering: exclude queries matching a blocklist of terms.
11. Implement a spell-correction-aware prefix search: if no results for exact
    prefix, try single-character edits (insertions, deletions, substitutions)
    on the last character and return suggestions.

DATA MODELS
-----------
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class TrieNode:
    children: dict[str, 'TrieNode'] = field(default_factory=dict)
    is_end: bool = False
    frequency: int = 0
    last_updated: float = 0.0
    top_k_cache: list[tuple[str, int]] = field(default_factory=list)

class AutocompleteTrie:
    def __init__(self, k: int = 10, decay_factor: float = 0.99): ...

    def insert(self, query: str, frequency: int = 1, timestamp: float = None): ...
    def increment(self, query: str, amount: int = 1, timestamp: float = None): ...
    def delete(self, query: str) -> bool: ...
    def get_frequency(self, query: str) -> int: ...

    def search_prefix(self, prefix: str, k: int = 5,
                      current_time: float = None) -> list[tuple[str, int]]: ...

    def get_all_queries(self) -> list[tuple[str, int]]:
        """Return all stored queries with frequencies."""
        ...

    def serialize(self) -> dict: ...

    @classmethod
    def deserialize(cls, data: dict) -> 'AutocompleteTrie': ...

    @property
    def size(self) -> int:
        """Number of unique queries stored."""
        ...

class QueryCollector:
    def __init__(self, trie: AutocompleteTrie): ...
    def record(self, query: str, timestamp: float = None): ...
    def flush(self): ...
    @property
    def buffer_size(self) -> int: ...

class AutocompleteService:
    def __init__(self, k: int = 5, decay_factor: float = 0.99,
                 blocklist: set[str] = None): ...

    def record_query(self, query: str, timestamp: float = None): ...
    def suggest(self, prefix: str, k: int = 5,
                current_time: float = None) -> list[str]: ...
    def suggest_with_scores(self, prefix: str, k: int = 5,
                            current_time: float = None) -> list[tuple[str, float]]: ...
    def fuzzy_suggest(self, prefix: str, k: int = 5,
                      current_time: float = None) -> list[str]: ...
    def add_to_blocklist(self, term: str): ...
    def get_stats(self) -> dict: ...

API SPECIFICATION
-----------------
# Direct trie usage
trie = AutocompleteTrie(k=10)
trie.insert("hello world", frequency=100)
trie.insert("hello there", frequency=50)
trie.insert("help me", frequency=30)
trie.insert("helicopter", frequency=20)

results = trie.search_prefix("hel", k=3)
# [("hello world", 100), ("hello there", 50), ("help me", 30)]

results = trie.search_prefix("hello", k=3)
# [("hello world", 100), ("hello there", 50)]

# Increment frequency
trie.increment("help me", amount=80)  # now frequency 110
results = trie.search_prefix("hel", k=2)
# [("help me", 110), ("hello world", 100)]

# Service usage
service = AutocompleteService(k=5, blocklist={"badword"})

# Record queries (simulating real search traffic)
queries = ["apple pie", "apple", "apple watch", "application", "apply"]
for q in queries:
    for _ in range(10):
        service.record_query(q, timestamp=1000.0)
service.record_query("apple pie", timestamp=1000.0)  # extra count

suggestions = service.suggest("app", k=5)
# ["apple pie", "apple", "apple watch", "application", "apply"]
# (apple pie first because highest frequency)

# Simulate typeahead as user types
for i in range(1, len("apple") + 1):
    prefix = "apple"[:i]
    results = service.suggest(prefix, k=3)
    print(f"'{prefix}' -> {results}")
# 'a' -> ['apple pie', 'apple', 'apple watch']
# 'ap' -> ['apple pie', 'apple', 'apple watch']
# 'app' -> ['apple pie', 'apple', 'apple watch']
# 'appl' -> ['apple pie', 'apple', 'apple watch']
# 'apple' -> ['apple pie', 'apple', 'apple watch']

# Fuzzy suggestions
results = service.fuzzy_suggest("aple", k=3)  # typo
# Should return apple-related suggestions

# Serialization
data = trie.serialize()
restored = AutocompleteTrie.deserialize(data)
assert restored.search_prefix("hel", k=3) == trie.search_prefix("hel", k=3)

EXAMPLE USAGE WITH ASSERTIONS
------------------------------
# Basic insert and search
trie = AutocompleteTrie()
trie.insert("cat", frequency=10)
trie.insert("car", frequency=20)
trie.insert("card", frequency=15)
trie.insert("care", frequency=5)

results = trie.search_prefix("ca", k=3)
assert results[0] == ("car", 20)
assert results[1] == ("card", 15)
assert results[2] == ("cat", 10)

# Exact match frequency
assert trie.get_frequency("car") == 20
assert trie.get_frequency("nonexistent") == 0

# Increment
trie.increment("cat", 15)  # now 25
results = trie.search_prefix("ca", k=1)
assert results[0] == ("cat", 25)

# Delete
trie.delete("cat")
assert trie.get_frequency("cat") == 0
results = trie.search_prefix("ca", k=10)
assert ("cat", 25) not in results

# Time-weighted decay
trie2 = AutocompleteTrie(decay_factor=0.5)  # aggressive decay for testing
trie2.insert("old query", frequency=100, timestamp=0.0)
trie2.insert("new query", frequency=50, timestamp=3600.0)  # 1 hour later

# At t=3600, "old query" decayed by 0.5^1 = 50, "new query" is fresh at 50
results = trie2.search_prefix("", k=2, current_time=3600.0)
# Both should be around 50, but new_query wins by freshness or tiebreak

# Empty prefix returns top-k across all queries
trie3 = AutocompleteTrie()
trie3.insert("alpha", 10)
trie3.insert("beta", 20)
trie3.insert("gamma", 30)
results = trie3.search_prefix("", k=2)
assert results[0] == ("gamma", 30)
assert results[1] == ("beta", 20)

# Phrase support
trie4 = AutocompleteTrie()
trie4.insert("new york pizza", 100)
trie4.insert("new york times", 80)
trie4.insert("new jersey", 50)
results = trie4.search_prefix("new york", k=2)
assert len(results) == 2
assert results[0][0] == "new york pizza"

# Serialization round-trip
data = trie.serialize()
restored = AutocompleteTrie.deserialize(data)
assert restored.size == trie.size

# Blocklist
service = AutocompleteService(blocklist={"banned"})
service.record_query("banned query")
service.record_query("good query")
results = service.suggest("", k=10)
assert all("banned" not in r for r in results)

CONSTRAINTS
-----------
- All data in-memory
- Trie nodes use dict for children (not array of 26 for a-z, since queries
  include spaces, numbers, and special characters)
- Top-k cache at each node bounded by k (default 10)
- Queries are case-insensitive (stored lowercase)
- Maximum query length: 200 characters
- Support up to 100,000 unique queries
- search_prefix should be O(p + k log k) where p is prefix length, thanks to top-k cache
- No external dependencies beyond Python standard library
- Target: 200-350 lines of code

TESTING REQUIREMENTS
--------------------
Write tests in test_search_autocomplete.py using pytest. Include these test cases:

1.  Insert and search returns correct top-k by frequency
2.  Search with prefix returns only matching completions
3.  Increment increases frequency and reranks results
4.  Delete removes query from trie and results
5.  Frequency tiebreaker is lexicographic ordering
6.  Time-weighted decay reduces old queries' effective frequency
7.  Empty prefix returns global top-k
8.  Phrase queries (multi-word) work correctly
9.  QueryCollector batches queries and flushes to trie
10. Serialization round-trip preserves all queries and frequencies
11. Blocklist filters excluded terms from results
12. Fuzzy suggest returns results for minor typos
13. Case insensitivity: "Apple" and "apple" are the same query
14. Top-k cache at nodes returns correct results without full traversal
15. Trie size property returns correct count of unique queries

IMPORTANT - EFFORT LEVEL: MINIMAL
Keep plan VERY brief (2-3 paragraphs max). Focus only on algorithm choice. Skip architectural discussions and detailed analysis.

Plan written to `PLAN.md`. 

Key points:

- **Single file** `search_autocomplete.py`, ~250-300 lines, plus `test_search_autocomplete.py`
- **Trie with top-k caches** rebuilt bottom-up along the insertion path (merge children's caches + self) — gives O(p + k) prefix search
- **Decay at read time** — caches store raw frequencies, decay is applied in `search_prefix` so caches don't go stale with time
- **Fuzzy search** edits only the last character of the prefix (per spec), tries ~53 variants
- **No branch pruning on delete** — just clear `is_end` and zero frequency, keeps code simple
- **Confidence: HIGH** — well-specified, standard data structures, trivial scale

[Committed changes to planner branch]