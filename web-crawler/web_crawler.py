"""Web crawler simulation demonstrating core crawling algorithms and data structures."""

import hashlib
import heapq
import math
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode


@dataclass
class WebPage:
    url: str
    content: str
    links: list[str] = field(default_factory=list)
    status_code: int = 200


class URLNormalizer:
    """Normalizes URLs for deduplication."""

    @staticmethod
    def normalize(url: str) -> str:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname.lower() if parsed.hostname else ""
        port = parsed.port
        path = parsed.path.rstrip("/") if parsed.path != "/" else ""
        # Sort query parameters
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        sorted_query = urlencode(
            sorted((k, v[0]) for k, v in query_params.items())
        ) if query_params else ""
        # Reconstruct without fragment
        netloc = host
        if port and not (scheme == "http" and port == 80) and not (scheme == "https" and port == 443):
            netloc = f"{host}:{port}"
        return urlunparse((scheme, netloc, path, "", sorted_query, ""))


class SimulatedWeb:
    """In-memory graph of web pages."""

    def __init__(self):
        self._pages: dict[str, WebPage] = {}
        self._robots: dict[str, str] = {}

    def add_page(self, page: WebPage):
        self._pages[URLNormalizer.normalize(page.url)] = page

    def set_robots_txt(self, domain: str, content: str):
        self._robots[domain] = content

    def fetch(self, url: str) -> Optional[WebPage]:
        return self._pages.get(URLNormalizer.normalize(url))

    def get_robots_txt(self, domain: str) -> Optional[str]:
        return self._robots.get(domain)


class BloomFilter:
    """Probabilistic set membership using bit array and double hashing."""

    def __init__(self, expected_items: int = 10000, fp_rate: float = 0.01):
        self._expected_items = expected_items
        self._fp_rate = fp_rate
        # Optimal size: m = -n*ln(p) / (ln2)^2
        self._m = max(1, int(-expected_items * math.log(fp_rate) / (math.log(2) ** 2)))
        # Optimal k: k = (m/n) * ln2
        self._k = max(1, int((self._m / expected_items) * math.log(2)))
        self._bits = bytearray((self._m + 7) // 8)
        self._count = 0
        self._false_positive_count = 0
        self._negative_check_count = 0

    def _get_hashes(self, item: str) -> list[int]:
        h = hashlib.md5(item.encode()).hexdigest()
        h1 = int(h[:16], 16)
        h2 = int(h[16:], 16)
        return [(h1 + i * h2) % self._m for i in range(self._k)]

    def _get_bit(self, pos: int) -> bool:
        return bool(self._bits[pos >> 3] & (1 << (pos & 7)))

    def _set_bit(self, pos: int):
        self._bits[pos >> 3] |= (1 << (pos & 7))

    def add(self, item: str):
        was_present = self.might_contain(item)
        if not was_present:
            self._negative_check_count -= 1  # undo the negative check count from might_contain
        for pos in self._get_hashes(item):
            self._set_bit(pos)
        self._count += 1

    def might_contain(self, item: str) -> bool:
        result = all(self._get_bit(pos) for pos in self._get_hashes(item))
        if not result:
            self._negative_check_count += 1
        return result

    @property
    def size_bits(self) -> int:
        return self._m

    @property
    def num_hash_functions(self) -> int:
        return self._k


class SimHash:
    """64-bit SimHash for content near-duplicate detection."""

    @staticmethod
    def compute(text: str) -> int:
        tokens = re.findall(r'\w+', text.lower())
        if not tokens:
            return 0
        v = [0] * 64
        for token in tokens:
            h = int(hashlib.md5(token.encode()).hexdigest(), 16) & ((1 << 64) - 1)
            for i in range(64):
                if h & (1 << i):
                    v[i] += 1
                else:
                    v[i] -= 1
        fingerprint = 0
        for i in range(64):
            if v[i] > 0:
                fingerprint |= (1 << i)
        return fingerprint

    @staticmethod
    def hamming_distance(hash1: int, hash2: int) -> int:
        x = hash1 ^ hash2
        return bin(x).count('1')

    @staticmethod
    def are_near_duplicates(hash1: int, hash2: int, threshold: int = 3) -> bool:
        return SimHash.hamming_distance(hash1, hash2) <= threshold


class RobotsParser:
    """Parses robots.txt and checks URL access permissions."""

    def __init__(self, robots_txt: str):
        self._rules: dict[str, list[tuple[str, str]]] = {}  # agent -> [(directive, path)]
        self._delays: dict[str, float] = {}
        self._parse(robots_txt)

    def _parse(self, text: str):
        current_agent = None
        for line in text.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ':' not in line:
                continue
            key, _, value = line.partition(':')
            key = key.strip().lower()
            value = value.strip()
            if key == 'user-agent':
                current_agent = value
                if current_agent not in self._rules:
                    self._rules[current_agent] = []
            elif current_agent is not None:
                if key in ('allow', 'disallow'):
                    if value:  # ignore empty directives
                        self._rules[current_agent].append((key, value))
                elif key == 'crawl-delay':
                    try:
                        self._delays[current_agent] = float(value)
                    except ValueError:
                        pass

    def is_allowed(self, path: str, user_agent: str = "*") -> bool:
        rules = self._rules.get(user_agent, self._rules.get("*", []))
        # Find the longest matching rule (standard robots.txt semantics)
        best_match = None
        best_len = -1
        for directive, rule_path in rules:
            if path.startswith(rule_path) and len(rule_path) > best_len:
                best_match = directive
                best_len = len(rule_path)
        if best_match is None:
            return True
        return best_match == "allow"

    def get_crawl_delay(self, user_agent: str = "*") -> Optional[float]:
        return self._delays.get(user_agent, self._delays.get("*"))


class URLFrontier:
    """Priority queue with politeness scheduling."""

    def __init__(self, strategy: str = "bfs", politeness_delay: float = 1.0):
        self._strategy = strategy
        self._politeness_delay = politeness_delay
        self._heap: list[tuple] = []
        self._seq = 0
        self._last_access: dict[str, float] = {}
        self._size = 0

    def add(self, url: str, priority: int = 0, depth: int = 0):
        if self._strategy == "dfs":
            seq = -self._seq  # negative for LIFO behavior in min-heap
        else:
            seq = self._seq
        heapq.heappush(self._heap, (priority, seq, url, depth))
        self._seq += 1
        self._size += 1

    def _get_host(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.hostname or ""

    def get_next(self, current_time: float = None) -> Optional[tuple[str, int]]:
        if current_time is None:
            current_time = time.time()
        # Try to find a URL whose host is not rate-limited
        deferred = []
        result = None
        while self._heap:
            entry = heapq.heappop(self._heap)
            _, _, url, depth = entry
            host = self._get_host(url)
            last = self._last_access.get(host, 0)
            if current_time - last >= self._politeness_delay:
                self._last_access[host] = current_time
                self._size -= 1
                result = (url, depth)
                break
            else:
                deferred.append(entry)
        # Put deferred items back
        for entry in deferred:
            heapq.heappush(self._heap, entry)
        return result

    def is_empty(self) -> bool:
        return self._size == 0

    @property
    def size(self) -> int:
        return self._size


@dataclass
class CrawlStats:
    pages_crawled: int = 0
    pages_skipped_duplicate: int = 0
    pages_skipped_robots: int = 0
    pages_skipped_bloom: int = 0
    urls_discovered: int = 0
    crawl_duration: float = 0.0


class Crawler:
    """Orchestrates web crawling with configurable strategies and limits."""

    def __init__(self, web: SimulatedWeb, seeds: list[str],
                 strategy: str = "bfs",
                 max_pages: int = 100,
                 max_depth: int = 10,
                 politeness_delay: float = 1.0,
                 duplicate_threshold: int = 3,
                 user_agent: str = "TestBot"):
        self._web = web
        self._seeds = seeds
        self._strategy = strategy
        self._max_pages = max_pages
        self._max_depth = max_depth
        self._duplicate_threshold = duplicate_threshold
        self._user_agent = user_agent
        self._frontier = URLFrontier(strategy=strategy, politeness_delay=politeness_delay)
        self._bloom = BloomFilter(expected_items=10000, fp_rate=0.01)
        self._seen_hashes: list[int] = []
        self._crawled_urls: list[str] = []
        self._page_graph: dict[str, list[str]] = {}
        self._robots_cache: dict[str, RobotsParser] = {}
        self._stats = CrawlStats()

    def _get_robots(self, domain: str) -> Optional[RobotsParser]:
        if domain not in self._robots_cache:
            txt = self._web.get_robots_txt(domain)
            if txt:
                self._robots_cache[domain] = RobotsParser(txt)
            else:
                self._robots_cache[domain] = None
        return self._robots_cache[domain]

    def _is_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        domain = parsed.hostname or ""
        parser = self._get_robots(domain)
        if parser is None:
            return True
        return parser.is_allowed(parsed.path, self._user_agent)

    def _extract_links(self, content: str) -> list[str]:
        return re.findall(r'href="([^"]*)"', content)

    def _is_duplicate_content(self, content: str) -> bool:
        h = SimHash.compute(content)
        for seen_h in self._seen_hashes:
            if SimHash.are_near_duplicates(h, seen_h, self._duplicate_threshold):
                return True
        self._seen_hashes.append(h)
        return False

    def crawl(self) -> CrawlStats:
        start_time = time.time()
        # Use a simulated clock for the frontier to avoid real delays
        sim_time = 0.0

        # Seed the frontier
        for seed in self._seeds:
            normalized = URLNormalizer.normalize(seed)
            self._bloom.add(normalized)
            self._frontier.add(normalized, priority=0, depth=0)

        while not self._frontier.is_empty() and self._stats.pages_crawled < self._max_pages:
            result = self._frontier.get_next(current_time=sim_time)
            if result is None:
                # All hosts rate-limited, advance time
                sim_time += self._frontier._politeness_delay
                continue

            url, depth = result

            # Check robots.txt
            if not self._is_allowed(url):
                self._stats.pages_skipped_robots += 1
                continue

            # Fetch page
            page = self._web.fetch(url)
            if page is None:
                continue

            # Check content duplication
            if self._is_duplicate_content(page.content):
                self._stats.pages_skipped_duplicate += 1
                continue

            # Record crawl
            self._stats.pages_crawled += 1
            self._crawled_urls.append(url)

            # Extract and process links
            extracted = self._extract_links(page.content)
            all_links = list(set(extracted + page.links))
            self._page_graph[url] = all_links

            if depth < self._max_depth:
                for link in all_links:
                    normalized = URLNormalizer.normalize(link)
                    self._stats.urls_discovered += 1
                    if not self._bloom.might_contain(normalized):
                        self._bloom.add(normalized)
                        self._frontier.add(normalized, priority=0, depth=depth + 1)

            sim_time += self._frontier._politeness_delay

        self._stats.crawl_duration = time.time() - start_time
        return self._stats

    def get_crawled_urls(self) -> list[str]:
        return list(self._crawled_urls)

    def get_page_graph(self) -> dict[str, list[str]]:
        return dict(self._page_graph)
