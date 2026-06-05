# Plan Review: News Feed System

## Plan Strengths

- Clean separation of concerns: `SocialGraph`, `PostStore`, and `NewsFeedService` each handle one responsibility.
- All three feed strategies (push, pull, hybrid) are implemented with correct mechanics: `deque(maxlen=N)` for push cache, `heapq.merge` for pull, celebrity threshold for hybrid.
- Feed cache invalidation on unfollow correctly removes the unfollowed user's posts from the push cache.
- `PostStore.create_post` uses `created_at if created_at is not None else 0.0` — avoids the `current_time or 0.0` falsy bug.
- Cursor-based pagination correctly filters `created_at < cursor` before ranking and slicing.

## Plan Gaps

1. **RELEVANCE_WEIGHT is too small to affect ranking.** `RELEVANCE_WEIGHT = 0.1` means the engagement bonus for 50 likes is `ln(51) * 0.1 ≈ 0.39`. Since timestamps are absolute values (100.0, 200.0, etc.), any time gap > 0.4 seconds overwhelms all engagement. Relevance ranking is effectively chronological. The `test_relevance_ranking` test fails because of this.

2. **Follow doesn't backfill the feed cache.** When a user follows someone who already has posts, the push cache gets nothing. The user won't see the followee's existing posts until they create a new one. Only affects fan-out-on-write/hybrid.

3. **`_remove_author_from_cache` crashes if a post was deleted.** `self.post_store.get_post(pid)` can return `None`, and `.author_id` on `None` raises `AttributeError`.

4. **`like` and `comment` on NewsFeedService discard return values.** `like_post` returns a bool (success/duplicate), `add_comment` returns a `Comment` — neither is surfaced to the caller.

5. **No `delete_post` functionality.** Posts persist forever. Feed caches can reference deleted posts (though `_get_feed_push` handles `None` with `if post:` check).

## Implementation Issues (1 test failure)

1. **`test_relevance_ranking` fails.** Old post at t=100 with 50 likes scores 100.39; new post at t=200 with 0 likes scores 200.0. The engagement bonus is negligible. **Fix:** Increase `RELEVANCE_WEIGHT` so engagement can meaningfully compete with recency.

2. **`_remove_author_from_cache` can raise `AttributeError`.** If a post_id in the cache references a deleted post, `get_post` returns `None` and the `.author_id` access crashes. **Fix:** Add a None check.

3. **Follow doesn't populate cache with existing posts.** After `follow("alice", "bob")`, alice's push cache is empty even if bob has 100 posts. The next `get_feed` call in push mode returns nothing from bob until bob posts again. **Fix:** Backfill the cache with the followee's recent posts on follow.
