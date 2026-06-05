# Plan (Iteration 1)

Task: URL SHORTENER
System Design Interview Vol 1 - Chapter 8

OVERVIEW
--------
Implement a URL shortening service similar to TinyURL or bit.ly as a
single-process Python application. The system converts long URLs into short,
unique codes using base62 encoding, handles hash collisions, supports custom
aliases, tracks click analytics, and enforces URL expiration. All data is
stored in-memory using dictionaries and lists.

REQUIREMENTS
------------
1.  Implement a URLShortener class that maps short codes to long URLs.
2.  Short code generation using base62 encoding (a-z, A-Z, 0-9) of an
    auto-incrementing counter. Codes should be 7 characters by default.
3.  Support an alternative hash-based approach: take first 7 characters of
    base62(SHA-256(long_url)). Handle collisions by appending a counter and
    rehashing until unique.
4.  Support custom short aliases: user provides a desired short code. Reject if
    already taken. Validate format (alphanumeric, 4-16 characters).
5.  URL validation: reject malformed URLs (must start with http:// or https://,
    valid domain structure).
6.  URL expiration: each shortened URL has an optional TTL (time-to-live) in seconds.
    Expired URLs return None on lookup. Default TTL is configurable (default: no expiration).
7.  Click analytics per short URL:
    - Total click count
    - Clicks per day (date histogram)
    - Last N click timestamps
    - Referrer tracking (optional referrer field in redirect request)
8.  Implement redirect: given a short code, return the original long URL (or None if
    not found or expired). Each redirect records an analytics event.
9.  Implement bulk shortening: shorten multiple URLs at once, return mapping.
10. Implement URL listing: list all active (non-expired) URLs with pagination
    (offset, limit).
11. Support a configurable domain prefix for display (e.g., "https://short.url/").
12. Implement rate limiting for URL creation: max N URLs per client per minute.

DATA MODELS
-----------
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class URLEntry:
    short_code: str
    long_url: str
    created_at: float
    expires_at: Optional[float] = None
    custom_alias: bool = False
    creator_id: Optional[str] = None
    click_count: int = 0
    click_history: list[dict] = field(default_factory=list)
    # click_history entries: {"timestamp": float, "referrer": str|None}

@dataclass
class AnalyticsReport:
    short_code: str
    total_clicks: int
    clicks_per_day: dict[str, int]  # {"2024-01-15": 42, ...}
    recent_clicks: list[dict]       # last N click events
    top_referrers: dict[str, int]   # {"google.com": 15, ...}

class URLShortener:
    def __init__(self, domain: str = "https://short.url",
                 default_ttl: Optional[float] = None,
                 code_length: int = 7,
                 strategy: str = "counter"): ...

    def shorten(self, long_url: str, custom_alias: Optional[str] = None,
                ttl: Optional[float] = None, creator_id: Optional[str] = None,
                current_time: float = None) -> str: ...

    def redirect(self, short_code: str, referrer: Optional[str] = None,
                 current_time: float = None) -> Optional[str]: ...

    def get_analytics(self, short_code: str) -> Optional[AnalyticsReport]: ...

    def bulk_shorten(self, urls: list[str], creator_id: Optional[str] = None,
                     current_time: float = None) -> dict[str, str]: ...

    def list_urls(self, offset: int = 0, limit: int = 20,
                  current_time: float = None) -> list[URLEntry]: ...

    def delete(self, short_code: str) -> bool: ...

class Base62:
    """Utility class for base62 encoding/decoding."""
    CHARSET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

    @staticmethod
    def encode(num: int) -> str: ...

    @staticmethod
    def decode(s: str) -> int: ...

API SPECIFICATION
-----------------
# Create shortener
shortener = URLShortener(domain="https://tny.im")

# Shorten a URL (counter-based)
short_url = shortener.shorten("https://www.example.com/very/long/path?query=value")
# Returns: "https://tny.im/0000001"

# Shorten with custom alias
short_url = shortener.shorten(
    "https://www.example.com/my-page",
    custom_alias="mypage"
)
# Returns: "https://tny.im/mypage"

# Shorten with expiration (1 hour)
short_url = shortener.shorten(
    "https://www.example.com/temp",
    ttl=3600,
    current_time=1000.0
)

# Redirect (lookup)
long_url = shortener.redirect("0000001")
# Returns: "https://www.example.com/very/long/path?query=value"

# Redirect with referrer tracking
long_url = shortener.redirect("0000001", referrer="https://google.com")

# Get analytics
report = shortener.get_analytics("0000001")
# report.total_clicks == 2
# report.clicks_per_day == {"2024-01-15": 2}

# Bulk shorten
results = shortener.bulk_shorten([
    "https://example.com/a",
    "https://example.com/b",
    "https://example.com/c"
])
# results == {"https://example.com/a": "https://tny.im/0000002", ...}

# List active URLs
urls = shortener.list_urls(offset=0, limit=10)

# Hash-based shortener
hash_shortener = URLShortener(strategy="hash")
short_url = hash_shortener.shorten("https://example.com/page")

# Base62 encoding
assert Base62.encode(0) == "0"
assert Base62.encode(61) == "Z"
assert Base62.encode(62) == "10"
assert Base62.decode("10") == 62

EXAMPLE USAGE WITH ASSERTIONS
------------------------------
# Basic shorten and redirect
s = URLShortener()
url = s.shorten("https://example.com/hello")
assert url.startswith("https://short.url/")
code = url.split("/")[-1]
assert s.redirect(code) == "https://example.com/hello"

# Custom alias
url = s.shorten("https://example.com/world", custom_alias="world")
assert url == "https://short.url/world"
assert s.redirect("world") == "https://example.com/world"

# Duplicate custom alias rejected
try:
    s.shorten("https://example.com/other", custom_alias="world")
    assert False, "Should have raised"
except ValueError:
    pass

# Expiration
url = s.shorten("https://example.com/temp", ttl=60, current_time=1000.0)
code = url.split("/")[-1]
assert s.redirect(code, current_time=1030.0) == "https://example.com/temp"  # not expired
assert s.redirect(code, current_time=1061.0) is None  # expired

# Invalid URL rejected
try:
    s.shorten("not-a-valid-url")
    assert False, "Should have raised"
except ValueError:
    pass

# Analytics tracking
s2 = URLShortener()
url = s2.shorten("https://example.com/tracked")
code = url.split("/")[-1]
for _ in range(5):
    s2.redirect(code, referrer="https://google.com")
for _ in range(3):
    s2.redirect(code, referrer="https://twitter.com")
report = s2.get_analytics(code)
assert report.total_clicks == 8
assert report.top_referrers["https://google.com"] == 5

# Base62 round-trip
for i in [0, 1, 61, 62, 999, 123456789, 2**40]:
    assert Base62.decode(Base62.encode(i)) == i

# Hash-based strategy produces same code for same URL
hs = URLShortener(strategy="hash")
url1 = hs.shorten("https://example.com/deterministic")
# Deterministic: same input -> same code (if not already taken)

CONSTRAINTS
-----------
- All data in-memory (dicts)
- Short codes: 7 characters default (base62 = 62^7 = ~3.5 trillion possibilities)
- Support up to 100,000 URLs in memory
- Click history per URL capped at last 1000 events to bound memory
- URL validation must catch obviously malformed URLs
- No external dependencies beyond Python standard library
- Target: 200-350 lines of code

TESTING REQUIREMENTS
--------------------
Write tests in test_url_shortener.py using pytest. Include these test cases:

1.  Shorten returns a valid short URL with the configured domain
2.  Redirect returns the original long URL
3.  Redirect returns None for unknown short code
4.  Custom alias works and is accessible
5.  Duplicate custom alias raises ValueError
6.  Invalid custom alias format (too short, special chars) raises ValueError
7.  URL expiration: redirect returns None after TTL
8.  URL expiration: redirect works before TTL
9.  Invalid URL (no scheme, no domain) raises ValueError
10. Analytics tracks click count correctly
11. Analytics tracks referrers correctly
12. Bulk shorten creates multiple short URLs
13. Base62 encode/decode round-trip is correct
14. Hash-based strategy handles collisions
15. Delete removes URL and redirect returns None

IMPORTANT - EFFORT LEVEL: MINIMAL
Keep plan VERY brief (2-3 paragraphs max). Focus only on algorithm choice. Skip architectural discussions and detailed analysis.

Plan written to `PLAN.md`. Summary:

- **Single file** `url_shortener.py` (~250 lines) with `Base62`, `URLEntry`, `AnalyticsReport`, `URLShortener`
- **Two strategies**: counter-based (zero-padded base62 of auto-incrementing int) and hash-based (base62 of SHA-256, collision handling via counter+rehash)
- **Storage**: `dict[str, URLEntry]` keyed by short code; rate limiting via `dict[str, list[float]]`
- **URL validation** via `urllib.parse.urlparse` (check scheme + netloc)
- **Click analytics**: append to capped list (1000 events), aggregate on demand into `AnalyticsReport`
- **Confidence: HIGH** — spec is fully detailed with data models, API signatures, and assertion-based examples

[Committed changes to planner branch]