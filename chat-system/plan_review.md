# Plan Review: Chat System

## Strengths

- Deterministic `dm:{sorted_ids}` conversation IDs avoid duplicate conversations without coordination.
- Per-conversation sequence numbers + global Lamport clock correctly separates local ordering from causal ordering.
- Lazy AWAY detection at query time avoids timers/background threads entirely.
- `last_seq - last_read_seq` for unread counts gives O(1) instead of scanning messages.
- Flat `dict[message_id, Message]` for O(1) edit/delete alongside the per-conversation message list.

## Gaps

1. **Offline queue flush is underspecified.** The summary says "flushed on `connect()`" but the requirements section is ambiguous about whether messages move from `offline_queue` to `inbox` on reconnect or just accumulate. The implementation inherited this ambiguity and doesn't flush.

2. **Unread counting doesn't account for sender's own messages.** The `last_seq - last_read_seq` formula counts the sender's own messages as unread for them. The plan doesn't address this edge case.

3. **Presence notifications are a requirement with no design.** Requirement 7 says "Presence change notifications sent to friends/contacts" but the data models and algorithm summary don't describe how this works. A `contacts` dict appeared in the implementation but wasn't in the plan's data models.

4. **No design for `get_conversations`.** It's in the API spec but has no discussion of how to avoid scanning all conversations. The implementation does a linear scan over all conversations.

5. **Pagination semantics are underspecified.** The plan says "bisect to find cursor position, slice" but doesn't cover the forward-without-cursor case or whether cursor values are inclusive or exclusive.

## Implementation Issues

- `connect()` doesn't flush the offline queue to inbox.
- `current_time or 0.0` treats an explicit `0.0` as falsy. Should be `current_time if current_time is not None else 0.0`.
- Presence change notifications to contacts are not implemented.
