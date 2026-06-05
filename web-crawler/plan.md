# Plan (Iteration 1)

Task: WEB CRAWLER
System Design Interview Vol 1 - Chapter 9

OVERVIEW
--------
Implement a web crawler simulation as a single-process Python application. The
crawler traverses a simulated web graph (not real HTTP), demonstrating the core
algorithms and data structures used in production crawlers: URL frontier with
politeness scheduling, URL deduplication using a Bloom filter, content
deduplication using SimHash, robots.txt parsing, and BFS/DFS traversal
strategies.

The "web" is simulated as an in-memory graph of pages. Each page has a URL,
HTML content, and outgoing links. The crawler discovers and processes pages
according to configurable strategies and constraints.

REQUIREMENTS
------------
1.  Implement a SimulatedWeb class that holds a graph of web pages. Each page has:
    - URL (string like "https://example.com/page1")
    - HTML content (string)
    - Links to other pages (list of URLs)
    - Optional robots.txt rules per domain
2.  Implement a URLFrontier that manages the queue of URLs to crawl:
    - Support BFS (FIFO queue) and DFS (LIFO stack) strategies.
    - Implement politeness: per-host rate limiting ensuring a minimum delay
      between requests to the same host (e.g., 1 second between crawls of
      same domain).
    - Priority queue support: URLs can have priorities (0 = highest).
    - Dequeue returns the highest-priority URL whose host is not rate-limited.
3.  Implement a BloomFilter for URL deduplication:
    - Configurable expected number of items and false positive rate.
    - Uses multiple hash functions (k hash functions computed via double hashing).
    - Methods: add(url), might_contain(url) -> bool.
    - Track actual false positive rate vs expected.
4.  Implement SimHash for content deduplication:
    - Compute a 64-bit fingerprint of text content.
    - Two pages are "near-duplicates" if their SimHash Hamming distance <= threshold (default 3).
    - Use word-level features with token hashing.
5.  Implement RobotsParser that parses robots.txt content:
    - Support User-agent, Allow, Disallow directives.
    - Method: is_allowed(url, user_agent="*") -> bool
    - Support Crawl-delay directive.
6.  Implement the Crawler class that orchestrates crawling:
    - Takes a SimulatedWeb, seed URLs, and configuration.
    - Crawl loop: dequeue URL from frontier, fetch page, extract links, add new
      links to frontier (if not seen and allowed by robots.txt).
    - Track: pages crawled, pages skipped (duplicate content), pages disallowed.
    - Maximum pages limit (stop after N pages).
    - Maximum depth limit (BFS depth from seed URLs).
7.  Implement link extraction: parse the simulated HTML content to find links
    (simple regex or string matching for <a href="..."> patterns).
8.  Implement crawl statistics: pages/second, unique pages found, duplicate
    pages detected, bloom filter stats.
9.  Support URL normalization: lowercase scheme and host, remove trailing slashes,
    remove fragments (#...), sort query parameters.
10. Implement a crawl report that summarizes the crawl results.

DATA MODELS
-----------
from dataclasses import dataclass, field
from typing import Optional
from collections import deque

@dataclass
class WebPage:
    url: str
    content: str
    links: list[str] = field(default_factory=list)
    status_code: int = 200

class SimulatedWeb:
    def __init__(self): ...
    def add_page(self, page: WebPage): ...
    def set_robots_txt(self, domain: str, content: str): ...
    def fetch(self, url: str) -> Optional[WebPage]: ...
    def get_robots_txt(self, domain: str) -> Optional[str]: ...

class BloomFilter:
    def __init__(self, expected_items: int = 10000, fp_rate: float = 0.01): ...
    def add(self, item: str): ...
    def might_contain(self, item: str) -> bool: ...
    @property
    def size_bits(self) -> int: ...
    @property
    def num_hash_functions(self) -> int: ...

class SimHash:
    @staticmethod
    def compute(text: str) -> int: ...

    @staticmethod
    def hamming_distance(hash1: int, hash2: int) -> int: ...

    @staticmethod
    def are_near_duplicates(hash1: int, hash2: int, threshold: int = 3) -> bool: ...

class RobotsParser:
    def __init__(self, robots_txt: str): ...
    def is_allowed(self, path: str, user_agent: str = "*") -> bool: ...
    def get_crawl_delay(self, user_agent: str = "*") -> Optional[float]: ...

class URLFrontier:
    def __init__(self, strategy: str = "bfs",
                 politeness_delay: float = 1.0): ...
    def add(self, url: str, priority: int = 0, depth: int = 0): ...
    def get_next(self, current_time: float = None) -> Optional[tuple[str, int]]:
        """Returns (url, depth) or None if frontier is empty/all hosts rate-limited."""
        ...
    def is_empty(self) -> bool: ...
    @property
    def size(self) -> int: ...

@dataclass
class CrawlStats:
    pages_crawled: int = 0
    pages_skipped_duplicate: int = 0
    pages_skipped_robots: int = 0
    pages_skipped_bloom: int = 0
    urls_discovered: int = 0
    crawl_duration: float = 0.0

class Crawler:
    def __init__(self, web: SimulatedWeb, seeds: list[str],
                 strategy: str = "bfs",
                 max_pages: int = 100,
                 max_depth: int = 10,
                 politeness_delay: float = 1.0,
                 duplicate_threshold: int = 3,
                 user_agent: str = "TestBot"): ...

    def crawl(self) -> CrawlStats: ...
    def get_crawled_urls(self) -> list[str]: ...
    def get_page_graph(self) -> dict[str, list[str]]: ...

class URLNormalizer:
    @staticmethod
    def normalize(url: str) -> str: ...

API SPECIFICATION
-----------------
# Build simulated web
web = SimulatedWeb()
web.add_page(WebPage(
    url="https://example.com/",
    content='<html><body>Home <a href="https://example.com/about">About</a></body></html>',
    links=["https://example.com/about", "https://example.com/contact"]
))
web.add_page(WebPage(
    url="https://example.com/about",
    content="<html><body>About us</body></html>",
    links=["https://example.com/"]
))
web.set_robots_txt("example.com", "User-agent: *\nDisallow: /private/\nCrawl-delay: 2")

# Create and run crawler
crawler = Crawler(
    web=web,
    seeds=["https://example.com/"],
    strategy="bfs",
    max_pages=50,
    max_depth=3
)
stats = crawler.crawl()
print(f"Crawled {stats.pages_crawled} pages")
print(f"Skipped {stats.pages_skipped_duplicate} duplicates")

# Bloom filter standalone
bf = BloomFilter(expected_items=1000, fp_rate=0.01)
bf.add("https://example.com/page1")
assert bf.might_contain("https://example.com/page1") == True
assert bf.might_contain("https://example.com/never-added") == False  # probably

# SimHash standalone
h1 = SimHash.compute("The quick brown fox jumps over the lazy dog")
h2 = SimHash.compute("The quick brown fox jumps over the lazy cat")
h3 = SimHash.compute("Completely different content about programming")
assert SimHash.hamming_distance(h1, h2) < 5   # near duplicates
assert SimHash.hamming_distance(h1, h3) > 10  # very different

# URL normalization
assert URLNormalizer.normalize("HTTPS://Example.COM/path/") == "https://example.com/path"
assert URLNormalizer.normalize("https://example.com/path#fragment") == "https://example.com/path"
assert URLNormalizer.normalize("https://example.com/path?b=2&a=1") == "https://example.com/path?a=1&b=2"

# Robots parser
parser = RobotsParser("User-agent: *\nDisallow: /private/\nAllow: /private/public/")
assert parser.is_allowed("/about") == True
assert parser.is_allowed("/private/secret") == False
assert parser.is_allowed("/private/public/page") == True

EXAMPLE USAGE WITH ASSERTIONS
------------------------------
# Build a small web graph
web = SimulatedWeb()
for i in range(10):
    links = [f"https://example.com/page{j}" for j in range(10) if j != i]
    web.add_page(WebPage(
        url=f"https://example.com/page{i}",
        content=f"<html>Page {i} content with unique text {i*17}</html>",
        links=links[:3]  # each page links to 3 others
    ))

crawler = Crawler(web=web, seeds=["https://example.com/page0"], max_pages=20)
stats = crawler.crawl()
assert stats.pages_crawled <= 10  # only 10 pages exist
assert stats.pages_crawled >= 1   # at least crawled the seed

# BFS respects depth
crawler2 = Crawler(web=web, seeds=["https://example.com/page0"], max_depth=1)
stats2 = crawler2.crawl()
assert stats2.pages_crawled <= 4  # seed + up to 3 linked pages

# Bloom filter has no false negatives
bf = BloomFilter(expected_items=100, fp_rate=0.01)
items = [f"url_{i}" for i in range(100)]
for item in items:
    bf.add(item)
for item in items:
    assert bf.might_contain(item) == True  # no false negatives

# SimHash near-duplicate detection
h1 = SimHash.compute("Hello world this is a test document")
h2 = SimHash.compute("Hello world this is a test document!")  # tiny change
assert SimHash.are_near_duplicates(h1, h2)

CONSTRAINTS
-----------
- All web content is simulated in-memory (no real HTTP requests)
- Bloom filter should use bit array (bytearray) not a set
- SimHash must be 64-bit
- URL frontier must support at least 10,000 URLs
- Crawler must terminate (max_pages or exhausted frontier)
- No external dependencies beyond Python standard library
- Target: 300-500 lines of code

TESTING REQUIREMENTS
--------------------
Write tests in test_web_crawler.py using pytest. Include these test cases:

1.  Bloom filter has zero false negatives for added items
2.  Bloom filter false positive rate is approximately as configured
3.  SimHash produces same hash for identical content
4.  SimHash detects near-duplicates (small edits -> small Hamming distance)
5.  SimHash distinguishes very different content (large Hamming distance)
6.  URL normalization lowercases scheme and host
7.  URL normalization removes fragments and sorts query params
8.  Robots parser correctly allows and disallows paths
9.  Robots parser handles Crawl-delay directive
10. URLFrontier BFS returns URLs in FIFO order
11. URLFrontier DFS returns URLs in LIFO order
12. Crawler respects max_pages limit
13. Crawler respects max_depth limit
14. Crawler skips URLs disallowed by robots.txt
15. Crawler detects and skips near-duplicate content

IMPORTANT - EFFORT LEVEL: MINIMAL
Keep plan VERY brief (2-3 paragraphs max). Focus only on algorithm choice. Skip architectural discussions and detailed analysis.

Plan written to `PLAN.md`. 

The spec is detailed enough that this is essentially an assembly task. Key decisions:

- **BloomFilter**: double hashing over `bytearray`, optimal k/m from standard formulas
- **SimHash**: word-level tokens hashed via `hashlib`, 64-bit fingerprint
- **URLFrontier**: `heapq` with `(priority, seq, url, depth)` — seq number handles BFS (ascending) vs DFS (descending)
- **Politeness**: per-host `last_access_time` dict, skip hosts still in cooldown
- **RobotsParser**: longest-match precedence for Allow/Disallow conflicts

Single file `web_crawler.py` (~400 lines), no external deps. Confidence: **HIGH**.

[Committed changes to planner branch]