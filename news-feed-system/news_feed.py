"""News Feed System - Fan-out-on-write, fan-out-on-read, and hybrid strategies."""

import heapq
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from math import log
from typing import Optional


class FeedStrategy(Enum):
    FAN_OUT_ON_WRITE = "push"
    FAN_OUT_ON_READ = "pull"
    HYBRID = "hybrid"


class RankingMode(Enum):
    CHRONOLOGICAL = "chronological"
    RELEVANCE = "relevance"


@dataclass
class Post:
    post_id: str
    author_id: str
    content: str
    created_at: float
    media_urls: list[str] = field(default_factory=list)
    likes_count: int = 0
    comments_count: int = 0
    liked_by: set[str] = field(default_factory=set)


@dataclass
class Comment:
    comment_id: str
    post_id: str
    author_id: str
    content: str
    created_at: float


@dataclass
class FeedItem:
    post: Post
    score: float = 0.0


class SocialGraph:
    """Manages follow/unfollow relationships between users."""

    def __init__(self):
        self._followers: dict[str, set[str]] = defaultdict(set)
        self._following: dict[str, set[str]] = defaultdict(set)

    def follow(self, follower_id: str, followee_id: str):
        self._followers[followee_id].add(follower_id)
        self._following[follower_id].add(followee_id)

    def unfollow(self, follower_id: str, followee_id: str):
        self._followers[followee_id].discard(follower_id)
        self._following[follower_id].discard(followee_id)

    def get_followers(self, user_id: str) -> set[str]:
        return set(self._followers[user_id])

    def get_following(self, user_id: str) -> set[str]:
        return set(self._following[user_id])

    def is_following(self, follower_id: str, followee_id: str) -> bool:
        return followee_id in self._following[follower_id]

    def get_follower_count(self, user_id: str) -> int:
        return len(self._followers[user_id])


class PostStore:
    """Stores posts and supports retrieval by author and time range."""

    def __init__(self):
        self._posts: dict[str, Post] = {}
        self._user_posts: dict[str, list[Post]] = defaultdict(list)
        self._comments: dict[str, list[Comment]] = defaultdict(list)

    def create_post(self, author_id: str, content: str, created_at: float = None,
                    media_urls: list[str] = None) -> Post:
        post = Post(
            post_id=str(uuid.uuid4()),
            author_id=author_id,
            content=content,
            created_at=created_at if created_at is not None else 0.0,
            media_urls=media_urls or [],
        )
        self._posts[post.post_id] = post
        self._user_posts[author_id].append(post)
        return post

    def get_post(self, post_id: str) -> Optional[Post]:
        return self._posts.get(post_id)

    def get_user_posts(self, user_id: str, limit: int = 50,
                       before: float = None) -> list[Post]:
        """Get posts by user, newest first, optionally before a timestamp."""
        posts = self._user_posts[user_id]
        if before is not None:
            posts = [p for p in posts if p.created_at < before]
        # Return newest first
        return sorted(posts, key=lambda p: p.created_at, reverse=True)[:limit]

    def like_post(self, user_id: str, post_id: str) -> bool:
        post = self._posts.get(post_id)
        if not post or user_id in post.liked_by:
            return False
        post.liked_by.add(user_id)
        post.likes_count += 1
        return True

    def add_comment(self, user_id: str, post_id: str, content: str,
                    created_at: float = None) -> Comment:
        post = self._posts.get(post_id)
        if not post:
            raise ValueError(f"Post {post_id} not found")
        comment = Comment(
            comment_id=str(uuid.uuid4()),
            post_id=post_id,
            author_id=user_id,
            content=content,
            created_at=created_at if created_at is not None else 0.0,
        )
        self._comments[post_id].append(comment)
        post.comments_count += 1
        return comment


class NewsFeedService:
    """News feed service supporting push, pull, and hybrid strategies."""

    RELEVANCE_WEIGHT = 50.0

    def __init__(self, strategy: FeedStrategy = FeedStrategy.FAN_OUT_ON_WRITE,
                 ranking: RankingMode = RankingMode.CHRONOLOGICAL,
                 celebrity_threshold: int = 1000,
                 cache_size: int = 500):
        self.strategy = strategy
        self.ranking = ranking
        self.celebrity_threshold = celebrity_threshold
        self.cache_size = cache_size
        self.graph = SocialGraph()
        self.post_store = PostStore()
        # Feed cache: user_id -> deque of post_ids (newest first)
        self._feed_cache: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=cache_size))

    def follow(self, follower_id: str, followee_id: str):
        self.graph.follow(follower_id, followee_id)
        if self.strategy in (FeedStrategy.FAN_OUT_ON_WRITE, FeedStrategy.HYBRID):
            if self.graph.get_follower_count(followee_id) <= self.celebrity_threshold:
                for post in self.post_store.get_user_posts(followee_id, limit=self.cache_size):
                    self._feed_cache[follower_id].append(post.post_id)

    def unfollow(self, follower_id: str, followee_id: str):
        self.graph.unfollow(follower_id, followee_id)
        # Invalidate feed cache for push-based strategies
        if self.strategy in (FeedStrategy.FAN_OUT_ON_WRITE, FeedStrategy.HYBRID):
            self._remove_author_from_cache(follower_id, followee_id)

    def _remove_author_from_cache(self, user_id: str, author_id: str):
        """Remove all posts by author_id from user_id's feed cache."""
        cache = self._feed_cache[user_id]
        filtered = []
        for pid in cache:
            post = self.post_store.get_post(pid)
            if post and post.author_id != author_id:
                filtered.append(pid)
        cache.clear()
        cache.extend(filtered)

    def create_post(self, author_id: str, content: str,
                    created_at: float = None, media_urls: list[str] = None) -> Post:
        post = self.post_store.create_post(author_id, content, created_at, media_urls)
        if self.strategy == FeedStrategy.FAN_OUT_ON_WRITE:
            self._fan_out_write(post)
        elif self.strategy == FeedStrategy.HYBRID:
            if self.graph.get_follower_count(author_id) <= self.celebrity_threshold:
                self._fan_out_write(post)
            # Celebrities: no fan-out, will be pulled on read
        # FAN_OUT_ON_READ: no action on write
        return post

    def _fan_out_write(self, post: Post):
        """Push post_id to all followers' feed caches."""
        for follower_id in self.graph.get_followers(post.author_id):
            self._feed_cache[follower_id].appendleft(post.post_id)

    def get_feed(self, user_id: str, page: int = 1, page_size: int = 20,
                 cursor: float = None) -> list[FeedItem]:
        if self.strategy == FeedStrategy.FAN_OUT_ON_WRITE:
            posts = self._get_feed_push(user_id)
        elif self.strategy == FeedStrategy.FAN_OUT_ON_READ:
            posts = self._get_feed_pull(user_id)
        else:
            posts = self._get_feed_hybrid(user_id)

        # Apply cursor filter
        if cursor is not None:
            posts = [p for p in posts if p.created_at < cursor]

        # Rank
        feed_items = [FeedItem(post=p, score=self._score(p)) for p in posts]
        feed_items.sort(key=lambda fi: fi.score, reverse=True)

        # Paginate
        start = (page - 1) * page_size
        return feed_items[start:start + page_size]

    def _score(self, post: Post) -> float:
        if self.ranking == RankingMode.CHRONOLOGICAL:
            return post.created_at
        # Relevance
        engagement = log(1 + post.likes_count + post.comments_count * 2)
        return post.created_at + engagement * self.RELEVANCE_WEIGHT

    def _get_feed_push(self, user_id: str) -> list[Post]:
        """Hydrate post IDs from feed cache."""
        posts = []
        for pid in self._feed_cache[user_id]:
            post = self.post_store.get_post(pid)
            if post:
                posts.append(post)
        return posts

    def _get_feed_pull(self, user_id: str) -> list[Post]:
        """Merge posts from all followed users."""
        following = self.graph.get_following(user_id)
        if not following:
            return []
        # Get each user's posts (already sorted newest-first)
        iterators = []
        for uid in following:
            user_posts = self.post_store.get_user_posts(uid)
            iterators.append(user_posts)
        # Merge using heapq (negate created_at for max-heap behavior)
        merged = heapq.merge(*iterators, key=lambda p: -p.created_at)
        return list(merged)

    def _get_feed_hybrid(self, user_id: str) -> list[Post]:
        """Merge push cache with pull from celebrities."""
        # Get push-cached posts
        push_posts = self._get_feed_push(user_id)

        # Pull from celebrity follows
        pull_posts = []
        for followee_id in self.graph.get_following(user_id):
            if self.graph.get_follower_count(followee_id) > self.celebrity_threshold:
                pull_posts.extend(self.post_store.get_user_posts(followee_id))

        # Merge and deduplicate
        seen = set()
        all_posts = []
        for p in push_posts + pull_posts:
            if p.post_id not in seen:
                seen.add(p.post_id)
                all_posts.append(p)
        return all_posts

    def like(self, user_id: str, post_id: str):
        self.post_store.like_post(user_id, post_id)

    def comment(self, user_id: str, post_id: str, content: str,
                created_at: float = None):
        self.post_store.add_comment(user_id, post_id, content, created_at)

    def get_stats(self) -> dict:
        return {
            "strategy": self.strategy.value,
            "ranking": self.ranking.value,
            "total_posts": len(self.post_store._posts),
            "cache_entries": sum(len(v) for v in self._feed_cache.values()),
        }
