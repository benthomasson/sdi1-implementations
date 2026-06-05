"""Tests for the News Feed System."""

import pytest
from news_feed import (
    FeedStrategy, RankingMode, NewsFeedService,
)


# 1. Follow/unfollow updates social graph correctly
def test_follow_unfollow():
    svc = NewsFeedService()
    svc.follow("alice", "bob")
    assert svc.graph.is_following("alice", "bob")
    assert "alice" in svc.graph.get_followers("bob")
    assert "bob" in svc.graph.get_following("alice")
    assert svc.graph.get_follower_count("bob") == 1

    svc.unfollow("alice", "bob")
    assert not svc.graph.is_following("alice", "bob")
    assert svc.graph.get_follower_count("bob") == 0


# 2. Post creation stores the post with correct fields
def test_post_creation():
    svc = NewsFeedService()
    post = svc.create_post("bob", "Hello!", created_at=1000.0)
    assert post.author_id == "bob"
    assert post.content == "Hello!"
    assert post.created_at == 1000.0
    assert post.likes_count == 0
    assert post.comments_count == 0
    stored = svc.post_store.get_post(post.post_id)
    assert stored is post


# 3. Fan-out-on-write delivers post to all followers' feeds
def test_fan_out_on_write_delivery():
    svc = NewsFeedService(strategy=FeedStrategy.FAN_OUT_ON_WRITE)
    svc.follow("alice", "bob")
    post = svc.create_post("bob", "Hello!", created_at=1000.0)
    feed = svc.get_feed("alice")
    assert len(feed) == 1
    assert feed[0].post.content == "Hello!"
    assert feed[0].post.author_id == "bob"


# 4. Fan-out-on-read computes feed from followed users' posts
def test_fan_out_on_read():
    svc = NewsFeedService(strategy=FeedStrategy.FAN_OUT_ON_READ)
    svc.follow("alice", "bob")
    post = svc.create_post("bob", "Hello!", created_at=1000.0)
    feed = svc.get_feed("alice")
    assert len(feed) == 1
    assert feed[0].post.content == "Hello!"


# 5. Feed is sorted by created_at descending (chronological mode)
def test_chronological_ordering():
    svc = NewsFeedService(strategy=FeedStrategy.FAN_OUT_ON_WRITE)
    svc.follow("alice", "bob")
    svc.create_post("bob", "First", created_at=1000.0)
    svc.create_post("bob", "Second", created_at=2000.0)
    svc.create_post("bob", "Third", created_at=3000.0)
    feed = svc.get_feed("alice")
    assert len(feed) == 3
    assert feed[0].post.created_at > feed[1].post.created_at > feed[2].post.created_at


# 6. Relevance ranking scores popular posts higher
def test_relevance_ranking():
    svc = NewsFeedService(
        strategy=FeedStrategy.FAN_OUT_ON_WRITE,
        ranking=RankingMode.RELEVANCE,
    )
    svc.follow("alice", "bob")
    old_popular = svc.create_post("bob", "Old but popular", created_at=100.0)
    svc.create_post("bob", "New but boring", created_at=200.0)
    # Like the old post many times
    for i in range(50):
        svc.like(f"user{i}", old_popular.post_id)
    feed = svc.get_feed("alice")
    assert feed[0].post.post_id == old_popular.post_id


# 7. Pagination returns correct page of results
def test_pagination():
    svc = NewsFeedService(strategy=FeedStrategy.FAN_OUT_ON_WRITE)
    svc.follow("alice", "bob")
    for i in range(5):
        svc.create_post("bob", f"Post {i}", created_at=float(1000 + i))
    page1 = svc.get_feed("alice", page=1, page_size=2)
    page2 = svc.get_feed("alice", page=2, page_size=2)
    page3 = svc.get_feed("alice", page=3, page_size=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1


# 8. Cursor-based pagination returns posts older than cursor
def test_cursor_pagination():
    svc = NewsFeedService(strategy=FeedStrategy.FAN_OUT_ON_WRITE)
    svc.follow("alice", "bob")
    for i in range(5):
        svc.create_post("bob", f"Post {i}", created_at=float(1000 + i))
    page1 = svc.get_feed("alice", page=1, page_size=2)
    cursor = page1[-1].post.created_at
    next_page = svc.get_feed("alice", cursor=cursor, page_size=2)
    assert len(next_page) == 2
    assert all(fi.post.created_at < cursor for fi in next_page)


# 9. Unfollow removes unfollowed user's posts from feed cache
def test_unfollow_removes_posts():
    svc = NewsFeedService(strategy=FeedStrategy.FAN_OUT_ON_WRITE)
    svc.follow("alice", "bob")
    svc.create_post("bob", "Post 1", created_at=1000.0)
    assert len(svc.get_feed("alice")) == 1
    svc.unfollow("alice", "bob")
    assert len(svc.get_feed("alice")) == 0


# 10. Like increments post's like count and updates liked_by set
def test_like():
    svc = NewsFeedService()
    post = svc.create_post("bob", "Post", created_at=1000.0)
    svc.like("alice", post.post_id)
    assert post.likes_count == 1
    assert "alice" in post.liked_by
    # Duplicate like should not increment
    svc.like("alice", post.post_id)
    assert post.likes_count == 1


# 11. Comment increments post's comment count
def test_comment():
    svc = NewsFeedService()
    post = svc.create_post("bob", "Post", created_at=1000.0)
    svc.comment("alice", post.post_id, "Great!")
    assert post.comments_count == 1
    svc.comment("charlie", post.post_id, "Nice!")
    assert post.comments_count == 2


# 12. Hybrid mode uses push for normal users, pull for celebrities
def test_hybrid_mode():
    svc = NewsFeedService(
        strategy=FeedStrategy.HYBRID,
        celebrity_threshold=5,
    )
    # Make "celeb" a celebrity by giving them > 5 followers
    for i in range(6):
        svc.follow(f"fan{i}", "celeb")
    svc.follow("alice", "celeb")
    svc.follow("alice", "bob")  # bob is normal

    bob_post = svc.create_post("bob", "Normal post", created_at=1000.0)
    celeb_post = svc.create_post("celeb", "Celebrity post", created_at=2000.0)

    # alice's push cache should have bob's post but not celeb's
    assert bob_post.post_id in svc._feed_cache["alice"]
    assert celeb_post.post_id not in svc._feed_cache["alice"]

    # But feed should include both (celeb pulled on read)
    feed = svc.get_feed("alice")
    post_ids = {fi.post.post_id for fi in feed}
    assert bob_post.post_id in post_ids
    assert celeb_post.post_id in post_ids


# 13. Feed cache respects max size limit
def test_feed_cache_max_size():
    cache_size = 10
    svc = NewsFeedService(
        strategy=FeedStrategy.FAN_OUT_ON_WRITE,
        cache_size=cache_size,
    )
    svc.follow("alice", "bob")
    for i in range(20):
        svc.create_post("bob", f"Post {i}", created_at=float(i))
    assert len(svc._feed_cache["alice"]) == cache_size
    # Cache should have the 10 most recent
    feed = svc.get_feed("alice", page_size=cache_size)
    assert feed[0].post.created_at == 19.0
    assert feed[-1].post.created_at == 10.0


# 14. Users who follow no one get empty feed
def test_empty_feed():
    svc = NewsFeedService(strategy=FeedStrategy.FAN_OUT_ON_WRITE)
    assert svc.get_feed("alice") == []
    svc2 = NewsFeedService(strategy=FeedStrategy.FAN_OUT_ON_READ)
    assert svc2.get_feed("alice") == []


# 15. Multiple followers all receive the post on fan-out-on-write
def test_multiple_followers_receive_post():
    svc = NewsFeedService(strategy=FeedStrategy.FAN_OUT_ON_WRITE)
    followers = ["alice", "charlie", "dave", "eve"]
    for f in followers:
        svc.follow(f, "bob")
    post = svc.create_post("bob", "Broadcast!", created_at=1000.0)
    for f in followers:
        feed = svc.get_feed(f)
        assert len(feed) == 1
        assert feed[0].post.post_id == post.post_id
