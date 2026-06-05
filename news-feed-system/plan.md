# Plan (Iteration 1)

Task: NEWS FEED SYSTEM
System Design Interview Vol 1 - Chapter 11

OVERVIEW
--------
Implement a news feed system that supports both fan-out-on-write (push model)
and fan-out-on-read (pull model) strategies. The system manages a social graph
(follow/unfollow), post creation, feed generation with time-based and
relevance-based ranking, and feed pagination. This is a single-process
in-memory Python application that demonstrates the architectural trade-offs
between push and pull models.

Fan-out-on-write: when a user posts, immediately write to all followers' feeds.
Fast reads, but expensive for users with many followers (celebrity problem).

Fan-out-on-read: when a user reads their feed, aggregate posts from all followed
users at read time. Cheap writes, but reads are slower.

The hybrid approach uses fan-out-on-write for normal users and fan-out-on-read
for celebrities (users with followers exceeding a threshold).

REQUIREMENTS
------------
1.  Implement a SocialGraph class managing follow/unfollow relationships.
    - follow(follower_id, followee_id)
    - unfollow(follower_id, followee_id)
    - get_followers(user_id) -> set of user IDs
    - get_following(user_id) -> set of user IDs
    - is_following(follower_id, followee_id) -> bool
    - get_follower_count(user_id) -> int
2.  Implement a Post data model with: post_id, author_id, content (text),
    created_at (timestamp), media_urls (optional list), likes_count, comments_count.
3.  Implement a PostStore that stores all posts and supports retrieval by author
    and by time range.
4.  Implement FanOutOnWrite feed strategy:
    - When a user creates a post, write the post_id to each follower's feed cache (a list).
    - Feed cache per user stores the most recent N post_ids (default 500).
    - Reading feed is a simple cache lookup + post hydration.
5.  Implement FanOutOnRead feed strategy:
    - No pre-computation on write.
    - On read, query posts from all followed users, merge-sort by timestamp,
      and return top N.
6.  Implement HybridFeed strategy:
    - Users with followers > celebrity_threshold (default 1000) use fan-out-on-read.
    - Normal users use fan-out-on-write.
    - On feed read: merge the user's fan-out-on-write cache with on-demand fetches
      from followed celebrities.
7.  Feed ranking:
    - Chronological: sort by created_at descending.
    - Relevance: score = base_time_score + engagement_bonus.
      engagement_bonus = log(1 + likes + comments * 2) * weight.
      base_time_score = created_at (higher = more recent = ranked higher).
    - Support switching between ranking modes.
8.  Feed pagination: get_feed(user_id, page, page_size) returning a page of posts.
    Support cursor-based pagination using the last post's timestamp as cursor.
9.  Post interactions: like(user_id, post_id), comment(user_id, post_id, text).
    These update the post's engagement counters and may affect ranking.
10. Implement feed cache invalidation: when a user unfollows someone, remove that
    person's posts from their feed cache.

DATA MODELS
-----------
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

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
    def __init__(self): ...
    def follow(self, follower_id: str, followee_id: str): ...
    def unfollow(self, follower_id: str, followee_id: str): ...
    def get_followers(self, user_id: str) -> set[str]: ...
    def get_following(self, user_id: str) -> set[str]: ...
    def is_following(self, follower_id: str, followee_id: str) -> bool: ...
    def get_follower_count(self, user_id: str) -> int: ...

class PostStore:
    def create_post(self, author_id: str, content: str, created_at: float = None,
                    media_urls: list[str] = None) -> Post: ...
    def get_post(self, post_id: str) -> Optional[Post]: ...
    def get_user_posts(self, user_id: str, limit: int = 50,
                       before: float = None) -> list[Post]: ...
    def like_post(self, user_id: str, post_id: str) -> bool: ...
    def add_comment(self, user_id: str, post_id: str, content: str,
                    created_at: float = None) -> Comment: ...

class NewsFeedService:
    def __init__(self, strategy: FeedStrategy = FeedStrategy.FAN_OUT_ON_WRITE,
                 ranking: RankingMode = RankingMode.CHRONOLOGICAL,
                 celebrity_threshold: int = 1000,
                 cache_size: int = 500): ...

    def create_post(self, author_id: str, content: str,
                    created_at: float = None) -> Post: ...
    def get_feed(self, user_id: str, page: int = 1, page_size: int = 20,
                 cursor: float = None) -> list[FeedItem]: ...
    def follow(self, follower_id: str, followee_id: str): ...
    def unfollow(self, follower_id: str, followee_id: str): ...
    def like(self, user_id: str, post_id: str): ...
    def comment(self, user_id: str, post_id: str, content: str,
                created_at: float = None): ...
    def get_stats(self) -> dict: ...

API SPECIFICATION
-----------------
# Create service with fan-out-on-write
service = NewsFeedService(
    strategy=FeedStrategy.FAN_OUT_ON_WRITE,
    ranking=RankingMode.CHRONOLOGICAL
)

# Build social graph
service.follow("alice", "bob")
service.follow("alice", "charlie")
service.follow("bob", "charlie")

# Create posts
post1 = service.create_post("bob", "Hello from Bob!", created_at=1000.0)
post2 = service.create_post("charlie", "Charlie's post", created_at=1001.0)
post3 = service.create_post("bob", "Another Bob post", created_at=1002.0)

# Alice follows bob and charlie, sees both in feed
feed = service.get_feed("alice", page=1, page_size=10)
# feed contains post3, post2, post1 (newest first)

# Pagination
page1 = service.get_feed("alice", page=1, page_size=2)
page2 = service.get_feed("alice", page=2, page_size=2)
# page1 has 2 items, page2 has 1 item

# Cursor-based pagination
cursor = page1[-1].post.created_at
next_page = service.get_feed("alice", cursor=cursor, page_size=2)

# Interactions
service.like("alice", post1.post_id)
service.comment("alice", post1.post_id, "Great post!")

# Fan-out-on-read mode
pull_service = NewsFeedService(strategy=FeedStrategy.FAN_OUT_ON_READ)
# ... same API, different internal behavior

# Hybrid mode
hybrid_service = NewsFeedService(
    strategy=FeedStrategy.HYBRID,
    celebrity_threshold=100  # lower for testing
)

# Unfollow removes posts from feed
service.unfollow("alice", "bob")
feed = service.get_feed("alice")
# Only charlie's posts remain

EXAMPLE USAGE WITH ASSERTIONS
------------------------------
# Fan-out-on-write: feed is pre-computed
service = NewsFeedService(strategy=FeedStrategy.FAN_OUT_ON_WRITE)
service.follow("alice", "bob")
post = service.create_post("bob", "Hello!", created_at=1000.0)
feed = service.get_feed("alice")
assert len(feed) == 1
assert feed[0].post.content == "Hello!"
assert feed[0].post.author_id == "bob"

# Fan-out-on-read: feed is computed on demand
service2 = NewsFeedService(strategy=FeedStrategy.FAN_OUT_ON_READ)
service2.follow("alice", "bob")
post = service2.create_post("bob", "Hello!", created_at=1000.0)
feed = service2.get_feed("alice")
assert len(feed) == 1
assert feed[0].post.content == "Hello!"

# Chronological ordering
service.create_post("bob", "Second post", created_at=2000.0)
feed = service.get_feed("alice")
assert feed[0].post.created_at > feed[1].post.created_at

# Relevance ranking boosts popular posts
service3 = NewsFeedService(ranking=RankingMode.RELEVANCE)
service3.follow("alice", "bob")
old_popular = service3.create_post("bob", "Old but popular", created_at=100.0)
new_boring = service3.create_post("bob", "New but boring", created_at=200.0)
# Like the old post many times
for u in [f"user{i}" for i in range(50)]:
    service3.like(u, old_popular.post_id)
feed = service3.get_feed("alice")
# old_popular should rank higher despite being older due to engagement

# Unfollow removes posts from feed (fan-out-on-write)
service4 = NewsFeedService(strategy=FeedStrategy.FAN_OUT_ON_WRITE)
service4.follow("alice", "bob")
service4.create_post("bob", "Post 1", created_at=1000.0)
assert len(service4.get_feed("alice")) == 1
service4.unfollow("alice", "bob")
assert len(service4.get_feed("alice")) == 0

# User doesn't see own posts in feed from follows, but does if self-follow not required
# Author's own posts are included in feed if they follow themselves or by default
service5 = NewsFeedService()
service5.follow("alice", "bob")
service5.create_post("alice", "My own post", created_at=1000.0)
service5.create_post("bob", "Bob's post", created_at=1001.0)
feed = service5.get_feed("alice")
assert len(feed) >= 1  # at minimum bob's post

CONSTRAINTS
-----------
- All data in-memory (dicts, lists, sets)
- Feed cache per user: max 500 most recent post IDs
- Post store should support thousands of posts
- Social graph should support thousands of follow relationships
- Feed generation (fan-out-on-read) should use merge-sort of sorted lists
- No external dependencies beyond Python standard library
- Target: 250-400 lines of code

TESTING REQUIREMENTS
--------------------
Write tests in test_news_feed.py using pytest. Include these test cases:

1.  Follow/unfollow updates social graph correctly
2.  Post creation stores the post with correct fields
3.  Fan-out-on-write delivers post to all followers' feeds
4.  Fan-out-on-read computes feed from followed users' posts
5.  Feed is sorted by created_at descending (chronological mode)
6.  Relevance ranking scores popular posts higher
7.  Pagination returns correct page of results
8.  Cursor-based pagination returns posts older than cursor
9.  Unfollow removes unfollowed user's posts from feed cache
10. Like increments post's like count and updates liked_by set
11. Comment increments post's comment count
12. Hybrid mode uses push for normal users, pull for celebrities
13. Feed cache respects max size limit
14. Users who follow no one get empty feed
15. Multiple followers all receive the post on fan-out-on-write

IMPORTANT - EFFORT LEVEL: MINIMAL
Keep plan VERY brief (2-3 paragraphs max). Focus only on algorithm choice. Skip architectural discussions and detailed analysis.

Plan written to `PLAN.md`. 

Key points:

- **Single file** `news_feed.py` (~300 lines) with `SocialGraph`, `PostStore`, `NewsFeedService`
- **Fan-out-on-write**: `defaultdict(deque)` of post IDs per user, capped at 500; push on create, filter on unfollow
- **Fan-out-on-read**: `heapq.merge` across followed users' sorted post lists at read time
- **Hybrid**: check follower count per author against threshold, merge push cache with pull from celebrities
- **Ranking**: chronological = sort by `created_at`; relevance = `created_at + log(1 + likes + comments*2) * 0.1`
- **Pagination**: offset-based slicing + cursor-based filtering by `created_at < cursor`
- **Confidence: HIGH** — well-specified requirements with clear data models and assertions

[Committed changes to planner branch]