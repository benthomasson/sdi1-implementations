"""Tests for the search autocomplete system."""

import pytest
from search_autocomplete import AutocompleteTrie, QueryCollector, AutocompleteService


class TestTrieInsertAndSearch:
    def test_basic_insert_and_search(self):
        trie = AutocompleteTrie()
        trie.insert("cat", frequency=10)
        trie.insert("car", frequency=20)
        trie.insert("card", frequency=15)
        trie.insert("care", frequency=5)

        results = trie.search_prefix("ca", k=3)
        assert results[0] == ("car", 20)
        assert results[1] == ("card", 15)
        assert results[2] == ("cat", 10)

    def test_search_returns_only_matching(self):
        trie = AutocompleteTrie()
        trie.insert("apple", 10)
        trie.insert("banana", 20)
        trie.insert("application", 5)

        results = trie.search_prefix("app", k=10)
        assert len(results) == 2
        queries = [q for q, _ in results]
        assert "apple" in queries
        assert "application" in queries
        assert "banana" not in queries

    def test_top_k_limits_results(self):
        trie = AutocompleteTrie()
        for i in range(20):
            trie.insert(f"query{i:02d}", frequency=i)

        results = trie.search_prefix("query", k=5)
        assert len(results) == 5
        assert results[0][1] == 19  # highest freq

    def test_empty_prefix_returns_global_topk(self):
        trie = AutocompleteTrie()
        trie.insert("alpha", 10)
        trie.insert("beta", 20)
        trie.insert("gamma", 30)

        results = trie.search_prefix("", k=2)
        assert results[0] == ("gamma", 30)
        assert results[1] == ("beta", 20)

    def test_no_results_for_nonexistent_prefix(self):
        trie = AutocompleteTrie()
        trie.insert("hello", 10)
        results = trie.search_prefix("xyz", k=5)
        assert results == []


class TestFrequency:
    def test_get_frequency(self):
        trie = AutocompleteTrie()
        trie.insert("car", frequency=20)
        assert trie.get_frequency("car") == 20
        assert trie.get_frequency("nonexistent") == 0

    def test_increment(self):
        trie = AutocompleteTrie()
        trie.insert("cat", frequency=10)
        trie.increment("cat", 15)
        assert trie.get_frequency("cat") == 25

        results = trie.search_prefix("ca", k=1)
        assert results[0] == ("cat", 25)

    def test_increment_inserts_if_missing(self):
        trie = AutocompleteTrie()
        trie.increment("newquery", 5)
        assert trie.get_frequency("newquery") == 5
        assert trie.size == 1

    def test_tiebreaker_is_lexicographic(self):
        trie = AutocompleteTrie()
        trie.insert("banana", 10)
        trie.insert("blueberry", 10)
        trie.insert("blackberry", 10)

        results = trie.search_prefix("b", k=3)
        queries = [q for q, _ in results]
        assert queries == ["banana", "blackberry", "blueberry"]


class TestDelete:
    def test_delete_removes_query(self):
        trie = AutocompleteTrie()
        trie.insert("cat", 25)
        trie.insert("car", 20)
        trie.delete("cat")

        assert trie.get_frequency("cat") == 0
        results = trie.search_prefix("ca", k=10)
        queries = [q for q, _ in results]
        assert "cat" not in queries

    def test_delete_nonexistent_returns_false(self):
        trie = AutocompleteTrie()
        assert trie.delete("nope") is False

    def test_delete_updates_size(self):
        trie = AutocompleteTrie()
        trie.insert("a", 1)
        trie.insert("b", 1)
        assert trie.size == 2
        trie.delete("a")
        assert trie.size == 1


class TestTimeDecay:
    def test_decay_reduces_old_queries(self):
        trie = AutocompleteTrie(decay_factor=0.5)
        trie.insert("old query", frequency=100, timestamp=0.0)
        trie.insert("new query", frequency=50, timestamp=3600.0)

        results = trie.search_prefix("", k=2, current_time=3600.0)
        # old: 100 * 0.5^1 = 50, new: 50 * 0.5^0 = 50
        # Tiebreaker: "new query" < "old query" lexicographically
        assert results[0][0] == "new query"
        assert results[1][0] == "old query"

    def test_no_decay_when_no_time(self):
        trie = AutocompleteTrie(decay_factor=0.5)
        trie.insert("test", frequency=100, timestamp=0.0)
        results = trie.search_prefix("", k=1)
        assert results[0] == ("test", 100)  # raw freq, no decay


class TestPhrases:
    def test_multiword_phrases(self):
        trie = AutocompleteTrie()
        trie.insert("new york pizza", 100)
        trie.insert("new york times", 80)
        trie.insert("new jersey", 50)

        results = trie.search_prefix("new york", k=2)
        assert len(results) == 2
        assert results[0][0] == "new york pizza"
        assert results[1][0] == "new york times"

    def test_phrase_prefix_matching(self):
        trie = AutocompleteTrie()
        trie.insert("hello world", 10)
        results = trie.search_prefix("hello ", k=5)
        assert len(results) == 1
        assert results[0][0] == "hello world"


class TestQueryCollector:
    def test_batch_flush(self):
        trie = AutocompleteTrie()
        collector = QueryCollector(trie)

        collector.record("apple", timestamp=1000.0)
        collector.record("apple", timestamp=1001.0)
        collector.record("banana", timestamp=1002.0)
        assert collector.buffer_size == 3

        collector.flush()
        assert collector.buffer_size == 0
        assert trie.get_frequency("apple") == 2
        assert trie.get_frequency("banana") == 1

    def test_aggregates_duplicates(self):
        trie = AutocompleteTrie()
        collector = QueryCollector(trie)

        for _ in range(5):
            collector.record("test", timestamp=100.0)
        collector.flush()
        assert trie.get_frequency("test") == 5


class TestSerialization:
    def test_round_trip(self):
        trie = AutocompleteTrie(k=10, decay_factor=0.95)
        trie.insert("hello", 100, timestamp=1000.0)
        trie.insert("help", 50, timestamp=2000.0)
        trie.insert("world", 75, timestamp=1500.0)

        data = trie.serialize()
        restored = AutocompleteTrie.deserialize(data)

        assert restored.size == trie.size
        assert restored.get_frequency("hello") == 100
        assert restored.get_frequency("help") == 50
        assert restored.get_frequency("world") == 75
        assert restored.search_prefix("hel", k=2) == trie.search_prefix("hel", k=2)

    def test_preserves_config(self):
        trie = AutocompleteTrie(k=5, decay_factor=0.8)
        data = trie.serialize()
        restored = AutocompleteTrie.deserialize(data)
        assert restored.k == 5
        assert restored.decay_factor == 0.8


class TestBlocklist:
    def test_blocklist_filters_results(self):
        service = AutocompleteService(blocklist={"banned"})
        service.record_query("banned query", timestamp=100.0)
        service.record_query("good query", timestamp=100.0)

        results = service.suggest("", k=10)
        assert "good query" in results
        assert all("banned" not in r for r in results)

    def test_add_to_blocklist(self):
        service = AutocompleteService()
        service.record_query("bad stuff", timestamp=100.0)
        service.add_to_blocklist("bad")
        results = service.suggest("", k=10)
        assert all("bad" not in r for r in results)


class TestFuzzySuggest:
    def test_fuzzy_with_typo(self):
        service = AutocompleteService()
        for _ in range(10):
            service.record_query("apple", timestamp=100.0)
            service.record_query("apple pie", timestamp=100.0)

        # "applt" has a typo in the last char; substituting 'e' for 't' -> "apple"
        results = service.fuzzy_suggest("applt", k=3)
        assert len(results) > 0
        assert any("apple" in r for r in results)

    def test_fuzzy_returns_exact_first(self):
        service = AutocompleteService()
        for _ in range(10):
            service.record_query("app", timestamp=100.0)

        results = service.fuzzy_suggest("app", k=3)
        assert "app" in results


class TestCaseInsensitivity:
    def test_case_insensitive(self):
        trie = AutocompleteTrie()
        trie.insert("Apple", frequency=10)
        trie.increment("APPLE", amount=5)

        assert trie.get_frequency("apple") == 15
        assert trie.size == 1

    def test_search_case_insensitive(self):
        trie = AutocompleteTrie()
        trie.insert("Hello World", 10)
        results = trie.search_prefix("HELLO", k=5)
        assert len(results) == 1


class TestTopKCache:
    def test_cache_updated_on_insert(self):
        trie = AutocompleteTrie(k=3)
        trie.insert("aaa", 10)
        trie.insert("aab", 20)
        trie.insert("aac", 30)
        trie.insert("aad", 5)

        # Cache should have top 3
        results = trie.search_prefix("aa", k=3)
        assert len(results) == 3
        assert results[0] == ("aac", 30)
        assert results[1] == ("aab", 20)
        assert results[2] == ("aaa", 10)
        # "aad" not in top 3


class TestTrieSize:
    def test_size_tracking(self):
        trie = AutocompleteTrie()
        assert trie.size == 0
        trie.insert("a", 1)
        assert trie.size == 1
        trie.insert("b", 1)
        assert trie.size == 2
        trie.insert("a", 5)  # re-insert same query
        assert trie.size == 2
        trie.delete("a")
        assert trie.size == 1


class TestService:
    def test_typeahead_simulation(self):
        service = AutocompleteService(k=5)
        queries = ["apple pie", "apple", "apple watch", "application", "apply"]
        for q in queries:
            for _ in range(10):
                service.record_query(q, timestamp=1000.0)
        service.record_query("apple pie", timestamp=1000.0)

        for i in range(1, len("apple") + 1):
            prefix = "apple"[:i]
            results = service.suggest(prefix, k=3)
            assert len(results) > 0
            assert results[0] == "apple pie"  # highest freq

    def test_suggest_with_scores(self):
        service = AutocompleteService()
        service.record_query("test", timestamp=100.0)
        results = service.suggest_with_scores("t", k=5)
        assert len(results) == 1
        assert results[0][0] == "test"
        assert results[0][1] == 1.0

    def test_get_stats(self):
        service = AutocompleteService(blocklist={"x"})
        service.record_query("hello", timestamp=100.0)
        stats = service.get_stats()
        assert stats["total_queries"] == 1
        assert stats["blocklist_size"] == 1
