"""Tests for web crawler simulation."""

import pytest
from web_crawler import (
    BloomFilter, SimHash, URLNormalizer, RobotsParser,
    URLFrontier, Crawler, SimulatedWeb, WebPage,
)


# 1. Bloom filter has zero false negatives
def test_bloom_filter_no_false_negatives():
    bf = BloomFilter(expected_items=100, fp_rate=0.01)
    items = [f"url_{i}" for i in range(100)]
    for item in items:
        bf.add(item)
    for item in items:
        assert bf.might_contain(item) is True


# 2. Bloom filter false positive rate is approximately as configured
def test_bloom_filter_false_positive_rate():
    bf = BloomFilter(expected_items=1000, fp_rate=0.01)
    for i in range(1000):
        bf.add(f"added_{i}")
    fp_count = sum(1 for i in range(10000) if bf.might_contain(f"not_added_{i}"))
    fp_rate = fp_count / 10000
    assert fp_rate < 0.05  # generous upper bound


# 3. SimHash produces same hash for identical content
def test_simhash_identical_content():
    text = "The quick brown fox jumps over the lazy dog"
    assert SimHash.compute(text) == SimHash.compute(text)


# 4. SimHash detects near-duplicates
def test_simhash_near_duplicates():
    h1 = SimHash.compute("Hello world this is a test document")
    h2 = SimHash.compute("Hello world this is a test document!")
    assert SimHash.are_near_duplicates(h1, h2)


# 5. SimHash distinguishes very different content
def test_simhash_different_content():
    h1 = SimHash.compute("The quick brown fox jumps over the lazy dog")
    h3 = SimHash.compute("Completely different content about programming")
    assert SimHash.hamming_distance(h1, h3) > 10


# 6. URL normalization lowercases scheme and host
def test_url_normalize_lowercase():
    assert URLNormalizer.normalize("HTTPS://Example.COM/path/") == "https://example.com/path"


# 7. URL normalization removes fragments and sorts query params
def test_url_normalize_fragments_and_query():
    assert URLNormalizer.normalize("https://example.com/path#fragment") == "https://example.com/path"
    assert URLNormalizer.normalize("https://example.com/path?b=2&a=1") == "https://example.com/path?a=1&b=2"


# 8. Robots parser correctly allows and disallows paths
def test_robots_parser_allow_disallow():
    parser = RobotsParser("User-agent: *\nDisallow: /private/\nAllow: /private/public/")
    assert parser.is_allowed("/about") is True
    assert parser.is_allowed("/private/secret") is False
    assert parser.is_allowed("/private/public/page") is True


# 9. Robots parser handles Crawl-delay directive
def test_robots_parser_crawl_delay():
    parser = RobotsParser("User-agent: *\nDisallow: /private/\nCrawl-delay: 2")
    assert parser.get_crawl_delay() == 2.0


# 10. URLFrontier BFS returns URLs in FIFO order
def test_frontier_bfs_order():
    f = URLFrontier(strategy="bfs", politeness_delay=0)
    f.add("https://a.com/1", depth=0)
    f.add("https://b.com/2", depth=0)
    f.add("https://c.com/3", depth=0)
    urls = [f.get_next(current_time=0)[0] for _ in range(3)]
    assert urls == ["https://a.com/1", "https://b.com/2", "https://c.com/3"]


# 11. URLFrontier DFS returns URLs in LIFO order
def test_frontier_dfs_order():
    f = URLFrontier(strategy="dfs", politeness_delay=0)
    f.add("https://a.com/1", depth=0)
    f.add("https://b.com/2", depth=0)
    f.add("https://c.com/3", depth=0)
    urls = [f.get_next(current_time=0)[0] for _ in range(3)]
    assert urls == ["https://c.com/3", "https://b.com/2", "https://a.com/1"]


# 12. Crawler respects max_pages limit
def test_crawler_max_pages():
    web = SimulatedWeb()
    for i in range(20):
        targets = [(i + 1 + j) % 20 for j in range(3)]
        links = [f"https://example.com/page{t}" for t in targets]
        web.add_page(WebPage(
            url=f"https://example.com/page{i}",
            content=f"<html>Page {i} unique content {i*17}</html>",
            links=links,
        ))
    crawler = Crawler(web=web, seeds=["https://example.com/page0"], max_pages=5, politeness_delay=0)
    stats = crawler.crawl()
    assert stats.pages_crawled == 5


# 13. Crawler respects max_depth limit
def test_crawler_max_depth():
    web = SimulatedWeb()
    # Linear chain: page0 -> page1 -> page2 -> page3 -> page4
    for i in range(5):
        next_link = [f"https://example.com/page{i+1}"] if i < 4 else []
        web.add_page(WebPage(
            url=f"https://example.com/page{i}",
            content=f"<html>Page {i} unique {i*31}</html>",
            links=next_link,
        ))
    crawler = Crawler(web=web, seeds=["https://example.com/page0"], max_depth=2, politeness_delay=0)
    stats = crawler.crawl()
    # depth 0: page0, depth 1: page1, depth 2: page2 -> max 3 pages
    assert stats.pages_crawled <= 3


# 14. Crawler skips URLs disallowed by robots.txt
def test_crawler_robots_disallow():
    web = SimulatedWeb()
    web.add_page(WebPage(
        url="https://example.com/",
        content='<html><a href="https://example.com/public">P</a> <a href="https://example.com/private/secret">S</a></html>',
        links=["https://example.com/public", "https://example.com/private/secret"],
    ))
    web.add_page(WebPage(
        url="https://example.com/public",
        content="<html>Public page</html>",
    ))
    web.add_page(WebPage(
        url="https://example.com/private/secret",
        content="<html>Secret page</html>",
    ))
    web.set_robots_txt("example.com", "User-agent: *\nDisallow: /private/")
    crawler = Crawler(web=web, seeds=["https://example.com/"], politeness_delay=0)
    stats = crawler.crawl()
    assert "https://example.com/private/secret" not in crawler.get_crawled_urls()
    assert stats.pages_skipped_robots >= 1


# 15. Crawler detects and skips near-duplicate content
def test_crawler_duplicate_content():
    web = SimulatedWeb()
    web.add_page(WebPage(
        url="https://example.com/page1",
        content="<html>This is the main content of the page about testing web crawlers</html>",
        links=["https://example.com/page2"],
    ))
    web.add_page(WebPage(
        url="https://example.com/page2",
        content="<html>This is the main content of the page about testing web crawlers</html>",  # exact dup
        links=[],
    ))
    crawler = Crawler(web=web, seeds=["https://example.com/page1"], politeness_delay=0)
    stats = crawler.crawl()
    assert stats.pages_crawled == 1
    assert stats.pages_skipped_duplicate == 1
