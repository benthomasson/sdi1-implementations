"""Tests for URL shortener."""

import pytest
from url_shortener import Base62, URLShortener


def test_shorten_returns_valid_url():
    s = URLShortener(domain="https://tny.im")
    url = s.shorten("https://example.com/hello")
    assert url.startswith("https://tny.im/")


def test_redirect_returns_original_url():
    s = URLShortener()
    url = s.shorten("https://example.com/hello")
    code = url.split("/")[-1]
    assert s.redirect(code) == "https://example.com/hello"


def test_redirect_returns_none_for_unknown():
    s = URLShortener()
    assert s.redirect("unknown") is None


def test_custom_alias_works():
    s = URLShortener()
    url = s.shorten("https://example.com/world", custom_alias="world")
    assert url == "https://short.url/world"
    assert s.redirect("world") == "https://example.com/world"


def test_duplicate_custom_alias_raises():
    s = URLShortener()
    s.shorten("https://example.com/a", custom_alias="taken")
    with pytest.raises(ValueError):
        s.shorten("https://example.com/b", custom_alias="taken")


def test_invalid_custom_alias_raises():
    s = URLShortener()
    with pytest.raises(ValueError):
        s.shorten("https://example.com/a", custom_alias="ab")  # too short
    with pytest.raises(ValueError):
        s.shorten("https://example.com/a", custom_alias="has-dash")  # special chars


def test_expiration_returns_none_after_ttl():
    s = URLShortener()
    url = s.shorten("https://example.com/temp", ttl=60, current_time=1000.0)
    code = url.split("/")[-1]
    assert s.redirect(code, current_time=1061.0) is None


def test_expiration_works_before_ttl():
    s = URLShortener()
    url = s.shorten("https://example.com/temp", ttl=60, current_time=1000.0)
    code = url.split("/")[-1]
    assert s.redirect(code, current_time=1030.0) == "https://example.com/temp"


def test_invalid_url_raises():
    s = URLShortener()
    with pytest.raises(ValueError):
        s.shorten("not-a-valid-url")
    with pytest.raises(ValueError):
        s.shorten("ftp://example.com/file")


def test_analytics_tracks_clicks():
    s = URLShortener()
    url = s.shorten("https://example.com/tracked")
    code = url.split("/")[-1]
    for _ in range(5):
        s.redirect(code)
    report = s.get_analytics(code)
    assert report.total_clicks == 5


def test_analytics_tracks_referrers():
    s = URLShortener()
    url = s.shorten("https://example.com/tracked")
    code = url.split("/")[-1]
    for _ in range(5):
        s.redirect(code, referrer="https://google.com")
    for _ in range(3):
        s.redirect(code, referrer="https://twitter.com")
    report = s.get_analytics(code)
    assert report.total_clicks == 8
    assert report.top_referrers["https://google.com"] == 5
    assert report.top_referrers["https://twitter.com"] == 3


def test_bulk_shorten():
    s = URLShortener()
    urls = ["https://example.com/a", "https://example.com/b", "https://example.com/c"]
    results = s.bulk_shorten(urls)
    assert len(results) == 3
    for url in urls:
        assert url in results
        code = results[url].split("/")[-1]
        assert s.redirect(code) == url


def test_base62_round_trip():
    for i in [0, 1, 61, 62, 999, 123456789, 2**40]:
        assert Base62.decode(Base62.encode(i)) == i


def test_hash_strategy_collision():
    hs = URLShortener(strategy="hash")
    url1 = hs.shorten("https://example.com/page1")
    url2 = hs.shorten("https://example.com/page2")
    assert url1 != url2
    code1 = url1.split("/")[-1]
    code2 = url2.split("/")[-1]
    assert hs.redirect(code1) == "https://example.com/page1"
    assert hs.redirect(code2) == "https://example.com/page2"


def test_delete_removes_url():
    s = URLShortener()
    url = s.shorten("https://example.com/delete-me")
    code = url.split("/")[-1]
    assert s.delete(code) is True
    assert s.redirect(code) is None
    assert s.delete(code) is False
