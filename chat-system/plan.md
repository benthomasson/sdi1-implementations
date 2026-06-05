# Plan (Iteration 1)

Task: CHAT SYSTEM
System Design Interview Vol 1 - Chapter 12

OVERVIEW
--------
Implement a chat system supporting 1:1 and group messaging as a single-process
Python application. The system simulates WebSocket-style connections, handles
message ordering with logical timestamps, tracks read receipts and online/
offline status, supports message history with cursor-based pagination, and
manages group chat membership. All communication happens through in-memory
method calls simulating a real-time messaging server.

REQUIREMENTS
------------
1.  Implement a ChatServer as the central message router and state manager.
2.  Implement UserConnection to simulate WebSocket connections:
    - Each user can connect/disconnect to the server.
    - Connected users receive messages in real-time (pushed to an inbox list).
    - Disconnected users receive messages when they reconnect (offline queue).
    - Track connection status: ONLINE, OFFLINE, AWAY (idle timeout).
3.  Implement 1:1 messaging (DirectMessage):
    - send_message(sender_id, recipient_id, content) -> Message
    - Messages are persisted in a conversation thread between two users.
    - Conversation ID is deterministic based on both user IDs (sorted).
4.  Implement group messaging (GroupChat):
    - create_group(creator_id, name, member_ids) -> group_id
    - send_group_message(sender_id, group_id, content) -> Message
    - add_member(group_id, user_id, added_by)
    - remove_member(group_id, user_id, removed_by)
    - Group messages are delivered to all members except the sender.
    - Maximum group size: 500 members.
5.  Message ordering:
    - Each message gets a server-assigned sequence number (monotonically increasing
      per conversation/group).
    - Messages also carry a Lamport timestamp for causal ordering across conversations.
    - Messages are stored in order and returned in order.
6.  Read receipts:
    - mark_read(user_id, conversation_id, up_to_message_id): marks all messages
      up to and including message_id as read by user_id.
    - get_unread_count(user_id, conversation_id) -> int
    - Read status is per-user per-conversation (the sequence number of the last
      read message).
7.  Presence / online status:
    - Users go ONLINE when connected, OFFLINE when disconnected.
    - AWAY after idle_timeout seconds of no activity (simulated via timestamps).
    - get_status(user_id) -> "online" | "offline" | "away"
    - Presence change notifications sent to friends/contacts.
8.  Message history with pagination:
    - get_history(conversation_id, cursor=None, limit=20, direction="backward")
    - cursor is the sequence number to paginate from.
    - "backward" returns older messages, "forward" returns newer messages.
    - Returns messages and a next_cursor for subsequent pages.
9.  Message types: text, image (URL), system (join/leave notifications).
10. Message editing and deletion:
    - edit_message(message_id, new_content) -> updates content, sets edited=True.
    - delete_message(message_id) -> soft delete, content replaced with "[deleted]".
11. Typing indicators: set_typing(user_id, conversation_id) and
    clear_typing(user_id, conversation_id). Get who is typing in a conversation.
12. Search messages within a conversation by keyword.

DATA MODELS
-----------
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    SYSTEM = "system"

class UserStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    AWAY = "away"

@dataclass
class Message:
    message_id: str
    conversation_id: str
    sender_id: str
    content: str
    message_type: MessageType = MessageType.TEXT
    timestamp: float = 0.0
    sequence_number: int = 0
    lamport_timestamp: int = 0
    edited: bool = False
    deleted: bool = False
    media_url: Optional[str] = None

@dataclass
class Conversation:
    conversation_id: str
    is_group: bool = False
    participants: set[str] = field(default_factory=set)
    messages: list[Message] = field(default_factory=list)
    next_sequence: int = 1

@dataclass
class GroupInfo:
    group_id: str
    name: str
    creator_id: str
    created_at: float
    members: set[str] = field(default_factory=set)
    admins: set[str] = field(default_factory=set)

@dataclass
class UserConnection:
    user_id: str
    status: UserStatus = UserStatus.OFFLINE
    last_active: float = 0.0
    inbox: list[Message] = field(default_factory=list)  # real-time delivery
    offline_queue: list[Message] = field(default_factory=list)
    connected_at: Optional[float] = None

class ChatServer:
    def __init__(self, idle_timeout: float = 300.0): ...

    # Connection management
    def connect(self, user_id: str, current_time: float = None): ...
    def disconnect(self, user_id: str, current_time: float = None): ...
    def heartbeat(self, user_id: str, current_time: float = None): ...
    def get_status(self, user_id: str, current_time: float = None) -> UserStatus: ...
    def get_online_users(self, current_time: float = None) -> list[str]: ...

    # Direct messaging
    def send_message(self, sender_id: str, recipient_id: str, content: str,
                     message_type: MessageType = MessageType.TEXT,
                     current_time: float = None) -> Message: ...

    # Group messaging
    def create_group(self, creator_id: str, name: str, member_ids: list[str],
                     current_time: float = None) -> str: ...
    def send_group_message(self, sender_id: str, group_id: str, content: str,
                           message_type: MessageType = MessageType.TEXT,
                           current_time: float = None) -> Message: ...
    def add_member(self, group_id: str, user_id: str, added_by: str): ...
    def remove_member(self, group_id: str, user_id: str, removed_by: str): ...
    def get_group_info(self, group_id: str) -> GroupInfo: ...

    # Read receipts
    def mark_read(self, user_id: str, conversation_id: str, up_to_message_id: str): ...
    def get_unread_count(self, user_id: str, conversation_id: str) -> int: ...

    # History
    def get_history(self, conversation_id: str, cursor: Optional[int] = None,
                    limit: int = 20, direction: str = "backward") -> tuple[list[Message], Optional[int]]: ...

    # Message operations
    def edit_message(self, user_id: str, message_id: str, new_content: str) -> Message: ...
    def delete_message(self, user_id: str, message_id: str) -> Message: ...

    # Typing indicators
    def set_typing(self, user_id: str, conversation_id: str, current_time: float = None): ...
    def clear_typing(self, user_id: str, conversation_id: str): ...
    def get_typing_users(self, conversation_id: str, current_time: float = None) -> list[str]: ...

    # Search
    def search_messages(self, conversation_id: str, query: str) -> list[Message]: ...

    # Conversations
    def get_conversations(self, user_id: str) -> list[Conversation]: ...

API SPECIFICATION
-----------------
server = ChatServer(idle_timeout=300.0)

# Users connect
server.connect("alice", current_time=1000.0)
server.connect("bob", current_time=1000.0)
assert server.get_status("alice") == UserStatus.ONLINE

# 1:1 messaging
msg = server.send_message("alice", "bob", "Hey Bob!", current_time=1000.0)
assert msg.sender_id == "alice"
assert msg.sequence_number == 1

# Bob receives in inbox (real-time)
bob_conn = server.connections["bob"]
assert len(bob_conn.inbox) == 1

# Group chat
group_id = server.create_group("alice", "Study Group", ["bob", "charlie"], current_time=1000.0)
msg = server.send_group_message("alice", group_id, "Welcome everyone!", current_time=1001.0)

# Read receipts
server.mark_read("bob", msg.conversation_id, msg.message_id)
assert server.get_unread_count("bob", msg.conversation_id) == 0

# History with pagination
msgs, next_cursor = server.get_history(msg.conversation_id, limit=10)

# Presence
server.disconnect("bob", current_time=2000.0)
assert server.get_status("bob") == UserStatus.OFFLINE

# Offline message queuing
server.send_message("alice", "bob", "Are you there?", current_time=2001.0)
# Bob reconnects and gets offline messages
server.connect("bob", current_time=3000.0)
assert len(server.connections["bob"].offline_queue) >= 1

# Typing indicator
server.set_typing("alice", msg.conversation_id, current_time=3000.0)
assert "alice" in server.get_typing_users(msg.conversation_id)

# Search
results = server.search_messages(msg.conversation_id, "Welcome")
assert len(results) >= 1

EXAMPLE USAGE WITH ASSERTIONS
------------------------------
server = ChatServer()

# Connect users
server.connect("alice", current_time=0.0)
server.connect("bob", current_time=0.0)

# Send direct message
msg1 = server.send_message("alice", "bob", "Hello Bob!", current_time=1.0)
assert msg1.conversation_id is not None
assert msg1.sequence_number == 1

msg2 = server.send_message("bob", "alice", "Hi Alice!", current_time=2.0)
assert msg2.conversation_id == msg1.conversation_id  # same conversation
assert msg2.sequence_number == 2

# Message history
messages, cursor = server.get_history(msg1.conversation_id, limit=10)
assert len(messages) == 2
assert messages[0].sequence_number > messages[1].sequence_number  # newest first in backward

# Group creation and messaging
gid = server.create_group("alice", "Friends", ["bob", "charlie"], current_time=3.0)
gmsg = server.send_group_message("alice", gid, "Group hello!", current_time=4.0)
info = server.get_group_info(gid)
assert "alice" in info.members
assert "bob" in info.members
assert "charlie" in info.members

# Unread count
assert server.get_unread_count("bob", gmsg.conversation_id) >= 1
server.mark_read("bob", gmsg.conversation_id, gmsg.message_id)
assert server.get_unread_count("bob", gmsg.conversation_id) == 0

# Edit message
edited = server.edit_message("alice", msg1.message_id, "Hello Bob! (edited)")
assert edited.edited == True
assert edited.content == "Hello Bob! (edited)"

# Delete message
deleted = server.delete_message("alice", msg1.message_id)
assert deleted.deleted == True

# Presence: away after idle
server.connect("alice", current_time=1000.0)
server.heartbeat("alice", current_time=1000.0)
assert server.get_status("alice", current_time=1100.0) == UserStatus.ONLINE  # within timeout
assert server.get_status("alice", current_time=1500.0) == UserStatus.AWAY    # past idle_timeout

# Offline queuing
server.disconnect("charlie", current_time=5.0)
server.send_group_message("alice", gid, "Charlie will see this later", current_time=6.0)
server.connect("charlie", current_time=10.0)
assert len(server.connections["charlie"].offline_queue) >= 1

CONSTRAINTS
-----------
- All data in-memory (dicts, lists)
- Message IDs: UUID4 strings
- Conversation ID for 1:1: deterministic from sorted user IDs
- Sequence numbers: monotonically increasing per conversation
- Lamport timestamps: global logical clock incremented on each message
- Group size limit: 500 members
- Message history pagination: default 20 messages per page
- No external dependencies beyond Python standard library
- Target: 300-450 lines of code

TESTING REQUIREMENTS
--------------------
Write tests in test_chat_system.py using pytest. Include these test cases:

1.  Send and receive 1:1 message between two connected users
2.  Messages have monotonically increasing sequence numbers per conversation
3.  Same 1:1 conversation ID regardless of who sends first
4.  Group creation includes all specified members plus creator
5.  Group message delivered to all members except sender
6.  Read receipt marks messages as read, unread count updates correctly
7.  Offline user receives messages in offline queue on reconnect
8.  Online/offline/away status transitions correctly
9.  Away status triggers after idle timeout
10. Message history pagination returns correct pages
11. Cursor-based pagination: backward returns older messages
12. Edit message updates content and sets edited flag
13. Delete message soft-deletes (content replaced)
14. Only sender can edit/delete their own messages
15. Typing indicators show/clear correctly

IMPORTANT - EFFORT LEVEL: MINIMAL
Keep plan VERY brief (2-3 paragraphs max). Focus only on algorithm choice. Skip architectural discussions and detailed analysis.

Plan written to `PLAN.md`. 

**Summary:** Single-file implementation with `ChatServer` owning all state in dicts. Key decisions:

- **Conversation ID**: deterministic `dm:{sorted_ids}` for 1:1
- **Message lookup**: flat `dict[message_id, Message]` for O(1) edit/delete
- **Sequence numbers**: per-conversation counter on `Conversation`
- **Lamport clock**: single global int, incremented per message
- **Pagination**: messages in insertion-order list, bisect to find cursor position, slice
- **Unread count**: `last_seq - last_read_seq` (read cursors stored per user×conversation)
- **Away detection**: lazy check at query time (`current_time - last_active > timeout`)
- **Offline delivery**: messages queued in `UserConnection.offline_queue`, flushed on `connect()`

[Committed changes to planner branch]