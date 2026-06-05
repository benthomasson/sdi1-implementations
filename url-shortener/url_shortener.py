"""URL shortening service with base62 encoding, analytics, and expiration."""

import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse


class Base62:
    """Utility class for base62 encoding/decoding."""
    CHARSET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

    @staticmethod
    def encode(num: int) -> str:
        if num == 0:
            return "0"
        chars = []
        while num > 0:
            chars.append(Base62.CHARSET[num % 62])
            num //= 62
        return "".join(reversed(chars))

    @staticmethod
    def decode(s: str) -> int:
        result = 0
        for c in s:
            result = result * 62 + Base62.CHARSET.index(c)
        return result


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


@dataclass
class AnalyticsReport:
    short_code: str
    total_clicks: int
    clicks_per_day: dict[str, int]
    recent_clicks: list[dict]
    top_referrers: dict[str, int]


class URLShortener:
    """URL shortening service with counter or hash-based strategies."""

    def __init__(self, domain: str = "https://short.url",
                 default_ttl: Optional[float] = None,
                 code_length: int = 7,
                 strategy: str = "counter",
                 rate_limit: int = 60):
        self.domain = domain.rstrip("/")
        self.default_ttl = default_ttl
        self.code_length = code_length
        self.strategy = strategy
        self.rate_limit = rate_limit
        self._counter = 0
        self._urls: dict[str, URLEntry] = {}
        self._rate_limits: dict[str, list[float]] = defaultdict(list)

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid URL scheme: {url}")
        if not parsed.netloc or "." not in parsed.netloc:
            raise ValueError(f"Invalid URL domain: {url}")

    def _validate_alias(self, alias: str) -> None:
        if not (4 <= len(alias) <= 16):
            raise ValueError(f"Custom alias must be 4-16 characters, got {len(alias)}")
        if not alias.isalnum():
            raise ValueError(f"Custom alias must be alphanumeric: {alias}")

    def _check_rate_limit(self, creator_id: str, now: float) -> None:
        timestamps = self._rate_limits[creator_id]
        cutoff = now - 60.0
        self._rate_limits[creator_id] = [t for t in timestamps if t > cutoff]
        if len(self._rate_limits[creator_id]) >= self.rate_limit:
            raise ValueError(f"Rate limit exceeded for {creator_id}")

    def _generate_counter_code(self) -> str:
        self._counter += 1
        encoded = Base62.encode(self._counter)
        return encoded.zfill(self.code_length)

    def _generate_hash_code(self, long_url: str) -> str:
        attempt = 0
        while True:
            data = long_url if attempt == 0 else f"{long_url}\x00{attempt}"
            digest = hashlib.sha256(data.encode()).digest()
            num = int.from_bytes(digest, "big")
            code = Base62.encode(num)[:self.code_length]
            if code not in self._urls:
                return code
            attempt += 1

    def shorten(self, long_url: str, custom_alias: Optional[str] = None,
                ttl: Optional[float] = None, creator_id: Optional[str] = None,
                current_time: Optional[float] = None) -> str:
        """Shorten a URL and return the full short URL."""
        self._validate_url(long_url)
        now = current_time if current_time is not None else time.time()

        if creator_id:
            self._check_rate_limit(creator_id, now)

        if custom_alias:
            self._validate_alias(custom_alias)
            if custom_alias in self._urls:
                raise ValueError(f"Custom alias already taken: {custom_alias}")
            code = custom_alias
        elif self.strategy == "hash":
            code = self._generate_hash_code(long_url)
        else:
            code = self._generate_counter_code()

        effective_ttl = ttl if ttl is not None else self.default_ttl
        expires_at = (now + effective_ttl) if effective_ttl is not None else None

        entry = URLEntry(
            short_code=code,
            long_url=long_url,
            created_at=now,
            expires_at=expires_at,
            custom_alias=custom_alias is not None,
            creator_id=creator_id,
        )
        self._urls[code] = entry

        if creator_id:
            self._rate_limits[creator_id].append(now)

        return f"{self.domain}/{code}"

    def redirect(self, short_code: str, referrer: Optional[str] = None,
                 current_time: Optional[float] = None) -> Optional[str]:
        """Look up a short code and return the original URL, or None."""
        entry = self._urls.get(short_code)
        if entry is None:
            return None

        now = current_time if current_time is not None else time.time()
        if entry.expires_at is not None and now > entry.expires_at:
            return None

        entry.click_count += 1
        click_event = {"timestamp": now, "referrer": referrer}
        entry.click_history.append(click_event)
        if len(entry.click_history) > 1000:
            entry.click_history = entry.click_history[-1000:]

        return entry.long_url

    def get_analytics(self, short_code: str) -> Optional[AnalyticsReport]:
        """Get analytics report for a short code."""
        entry = self._urls.get(short_code)
        if entry is None:
            return None

        clicks_per_day: dict[str, int] = defaultdict(int)
        referrer_counts: dict[str, int] = defaultdict(int)

        for click in entry.click_history:
            day = datetime.fromtimestamp(click["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d")
            clicks_per_day[day] += 1
            if click.get("referrer"):
                referrer_counts[click["referrer"]] += 1

        return AnalyticsReport(
            short_code=short_code,
            total_clicks=entry.click_count,
            clicks_per_day=dict(clicks_per_day),
            recent_clicks=entry.click_history[-10:],
            top_referrers=dict(referrer_counts),
        )

    def bulk_shorten(self, urls: list[str], creator_id: Optional[str] = None,
                     current_time: Optional[float] = None) -> dict[str, str]:
        """Shorten multiple URLs at once."""
        return {url: self.shorten(url, creator_id=creator_id, current_time=current_time)
                for url in urls}

    def list_urls(self, offset: int = 0, limit: int = 20,
                  current_time: Optional[float] = None) -> list[URLEntry]:
        """List active (non-expired) URLs with pagination."""
        now = current_time if current_time is not None else time.time()
        active = [e for e in self._urls.values()
                  if e.expires_at is None or now <= e.expires_at]
        return active[offset:offset + limit]

    def delete(self, short_code: str) -> bool:
        """Delete a short URL. Returns True if it existed."""
        if short_code in self._urls:
            del self._urls[short_code]
            return True
        return False
