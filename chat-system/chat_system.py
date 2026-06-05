"""Chat system supporting 1:1 and group messaging."""

import uuid
import bisect
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
    participants: set = field(default_factory=set)
    messages: list = field(default_factory=list)
    next_sequence: int = 1


@dataclass
class GroupInfo:
    group_id: str
    name: str
    creator_id: str
    created_at: float
    members: set = field(default_factory=set)
    admins: set = field(default_factory=set)


@dataclass
class UserConnection:
    user_id: str
    status: UserStatus = UserStatus.OFFLINE
    last_active: float = 0.0
    inbox: list = field(default_factory=list)
    offline_queue: list = field(default_factory=list)
    connected_at: Optional[float] = None


class ChatServer:
    """Central message router and state manager."""

    def __init__(self, idle_timeout: float = 300.0):
        self.idle_timeout = idle_timeout
        self.connections: dict[str, UserConnection] = {}
        self.conversations: dict[str, Conversation] = {}
        self.groups: dict[str, GroupInfo] = {}
        self.messages: dict[str, Message] = {}  # message_id -> Message
        self.read_cursors: dict[tuple, int] = {}  # (user_id, conv_id) -> last_read_seq
        self.typing: dict[tuple, float] = {}  # (user_id, conv_id) -> timestamp
        self.lamport_clock: int = 0
        self.contacts: dict[str, set] = {}  # user_id -> set of contact user_ids
        self.user_conversations: dict[str, set] = {}  # user_id -> set of conversation_ids

    def _get_or_create_connection(self, user_id: str) -> UserConnection:
        if user_id not in self.connections:
            self.connections[user_id] = UserConnection(user_id=user_id)
        return self.connections[user_id]

    def _dm_conversation_id(self, a: str, b: str) -> str:
        u1, u2 = sorted([a, b])
        return f"dm:{u1}:{u2}"

    def _deliver(self, user_id: str, msg: Message):
        """Deliver message to a user's inbox or offline queue."""
        conn = self._get_or_create_connection(user_id)
        if conn.status in (UserStatus.ONLINE, UserStatus.AWAY):
            conn.inbox.append(msg)
        else:
            conn.offline_queue.append(msg)

    # -- Connection management --

    def connect(self, user_id: str, current_time: float = None):
        current_time = current_time if current_time is not None else 0.0
        conn = self._get_or_create_connection(user_id)
        conn.status = UserStatus.ONLINE
        conn.last_active = current_time
        conn.connected_at = current_time
        # Flush offline queue to inbox
        if conn.offline_queue:
            conn.inbox.extend(conn.offline_queue)
            conn.offline_queue.clear()
        # Notify contacts of presence change
        for contact_id in self.contacts.get(user_id, set()):
            contact = self._get_or_create_connection(contact_id)
            if contact.status in (UserStatus.ONLINE, UserStatus.AWAY):
                contact.inbox.append(Message(
                    message_id=str(uuid.uuid4()),
                    conversation_id=self._dm_conversation_id(user_id, contact_id),
                    sender_id=user_id,
                    content=f"{user_id} is now online",
                    message_type=MessageType.SYSTEM,
                    timestamp=current_time,
                ))

    def disconnect(self, user_id: str, current_time: float = None):
        current_time = current_time if current_time is not None else 0.0
        conn = self._get_or_create_connection(user_id)
        conn.status = UserStatus.OFFLINE
        conn.last_active = current_time
        conn.connected_at = None
        for contact_id in self.contacts.get(user_id, set()):
            contact = self._get_or_create_connection(contact_id)
            if contact.status in (UserStatus.ONLINE, UserStatus.AWAY):
                contact.inbox.append(Message(
                    message_id=str(uuid.uuid4()),
                    conversation_id=self._dm_conversation_id(user_id, contact_id),
                    sender_id=user_id,
                    content=f"{user_id} is now offline",
                    message_type=MessageType.SYSTEM,
                    timestamp=current_time,
                ))

    def heartbeat(self, user_id: str, current_time: float = None):
        current_time = current_time if current_time is not None else 0.0
        conn = self._get_or_create_connection(user_id)
        conn.last_active = current_time
        if conn.status != UserStatus.OFFLINE:
            conn.status = UserStatus.ONLINE

    def get_status(self, user_id: str, current_time: float = None) -> UserStatus:
        conn = self._get_or_create_connection(user_id)
        if conn.status == UserStatus.OFFLINE:
            return UserStatus.OFFLINE
        if current_time is not None and (current_time - conn.last_active) > self.idle_timeout:
            conn.status = UserStatus.AWAY
            return UserStatus.AWAY
        return conn.status

    def get_online_users(self, current_time: float = None) -> list[str]:
        result = []
        for uid, conn in self.connections.items():
            status = self.get_status(uid, current_time)
            if status == UserStatus.ONLINE:
                result.append(uid)
        return result

    # -- Direct messaging --

    def send_message(self, sender_id: str, recipient_id: str, content: str,
                     message_type: MessageType = MessageType.TEXT,
                     current_time: float = None) -> Message:
        current_time = current_time if current_time is not None else 0.0
        conv_id = self._dm_conversation_id(sender_id, recipient_id)

        if conv_id not in self.conversations:
            self.conversations[conv_id] = Conversation(
                conversation_id=conv_id,
                participants={sender_id, recipient_id}
            )
        conv = self.conversations[conv_id]
        conv.participants.add(sender_id)
        conv.participants.add(recipient_id)

        self.lamport_clock += 1
        seq = conv.next_sequence
        conv.next_sequence += 1

        msg = Message(
            message_id=str(uuid.uuid4()),
            conversation_id=conv_id,
            sender_id=sender_id,
            content=content,
            message_type=message_type,
            timestamp=current_time,
            sequence_number=seq,
            lamport_timestamp=self.lamport_clock,
        )
        conv.messages.append(msg)
        self.messages[msg.message_id] = msg

        # Update sender activity
        self._get_or_create_connection(sender_id).last_active = current_time

        # Sender's own messages are always read
        self.read_cursors[(sender_id, conv_id)] = seq

        # Deliver to recipient
        self._deliver(recipient_id, msg)

        # Add contacts and conversation index
        self.contacts.setdefault(sender_id, set()).add(recipient_id)
        self.contacts.setdefault(recipient_id, set()).add(sender_id)
        self.user_conversations.setdefault(sender_id, set()).add(conv_id)
        self.user_conversations.setdefault(recipient_id, set()).add(conv_id)

        return msg

    # -- Group messaging --

    def create_group(self, creator_id: str, name: str, member_ids: list[str],
                     current_time: float = None) -> str:
        current_time = current_time if current_time is not None else 0.0
        group_id = f"group:{uuid.uuid4()}"
        members = set(member_ids) | {creator_id}

        self.groups[group_id] = GroupInfo(
            group_id=group_id,
            name=name,
            creator_id=creator_id,
            created_at=current_time,
            members=members,
            admins={creator_id},
        )
        self.conversations[group_id] = Conversation(
            conversation_id=group_id,
            is_group=True,
            participants=set(members),
        )
        for mid in members:
            self.user_conversations.setdefault(mid, set()).add(group_id)
        return group_id

    def send_group_message(self, sender_id: str, group_id: str, content: str,
                           message_type: MessageType = MessageType.TEXT,
                           current_time: float = None) -> Message:
        current_time = current_time if current_time is not None else 0.0
        group = self.groups[group_id]
        if sender_id not in group.members:
            raise ValueError("Sender is not a member of this group")

        conv = self.conversations[group_id]
        self.lamport_clock += 1
        seq = conv.next_sequence
        conv.next_sequence += 1

        msg = Message(
            message_id=str(uuid.uuid4()),
            conversation_id=group_id,
            sender_id=sender_id,
            content=content,
            message_type=message_type,
            timestamp=current_time,
            sequence_number=seq,
            lamport_timestamp=self.lamport_clock,
        )
        conv.messages.append(msg)
        self.messages[msg.message_id] = msg

        self._get_or_create_connection(sender_id).last_active = current_time
        self.read_cursors[(sender_id, group_id)] = seq

        for member_id in group.members:
            if member_id != sender_id:
                self._deliver(member_id, msg)

        return msg

    def add_member(self, group_id: str, user_id: str, added_by: str):
        group = self.groups[group_id]
        if len(group.members) >= 500:
            raise ValueError("Group size limit reached (500)")
        group.members.add(user_id)
        self.conversations[group_id].participants.add(user_id)
        self.user_conversations.setdefault(user_id, set()).add(group_id)

        # System message
        sys_msg = Message(
            message_id=str(uuid.uuid4()),
            conversation_id=group_id,
            sender_id=added_by,
            content=f"{user_id} was added by {added_by}",
            message_type=MessageType.SYSTEM,
            sequence_number=self.conversations[group_id].next_sequence,
        )
        self.lamport_clock += 1
        sys_msg.lamport_timestamp = self.lamport_clock
        self.conversations[group_id].next_sequence += 1
        self.conversations[group_id].messages.append(sys_msg)
        self.messages[sys_msg.message_id] = sys_msg

    def remove_member(self, group_id: str, user_id: str, removed_by: str):
        group = self.groups[group_id]
        group.members.discard(user_id)
        self.conversations[group_id].participants.discard(user_id)

        sys_msg = Message(
            message_id=str(uuid.uuid4()),
            conversation_id=group_id,
            sender_id=removed_by,
            content=f"{user_id} was removed by {removed_by}",
            message_type=MessageType.SYSTEM,
            sequence_number=self.conversations[group_id].next_sequence,
        )
        self.lamport_clock += 1
        sys_msg.lamport_timestamp = self.lamport_clock
        self.conversations[group_id].next_sequence += 1
        self.conversations[group_id].messages.append(sys_msg)
        self.messages[sys_msg.message_id] = sys_msg

    def get_group_info(self, group_id: str) -> GroupInfo:
        return self.groups[group_id]

    # -- Read receipts --

    def mark_read(self, user_id: str, conversation_id: str, up_to_message_id: str):
        msg = self.messages[up_to_message_id]
        key = (user_id, conversation_id)
        current = self.read_cursors.get(key, 0)
        if msg.sequence_number > current:
            self.read_cursors[key] = msg.sequence_number

    def get_unread_count(self, user_id: str, conversation_id: str) -> int:
        conv = self.conversations.get(conversation_id)
        if not conv or not conv.messages:
            return 0
        last_seq = conv.next_sequence - 1
        last_read = self.read_cursors.get((user_id, conversation_id), 0)
        return max(0, last_seq - last_read)

    # -- History with pagination --

    def get_history(self, conversation_id: str, cursor: Optional[int] = None,
                    limit: int = 20, direction: str = "backward") -> tuple:
        conv = self.conversations.get(conversation_id)
        if not conv or not conv.messages:
            return ([], None)

        msgs = conv.messages  # sorted by sequence_number (insertion order)

        if cursor is None:
            if direction == "backward":
                # Start from the end
                end = len(msgs)
                start = max(0, end - limit)
                page = list(reversed(msgs[start:end]))
                next_cursor = msgs[start].sequence_number if start > 0 else None
            else:
                end = min(limit, len(msgs))
                page = msgs[:end]
                next_cursor = page[-1].sequence_number if end < len(msgs) else None
        else:
            # Find cursor position using sequence numbers
            seq_nums = [m.sequence_number for m in msgs]
            idx = bisect.bisect_left(seq_nums, cursor)

            if direction == "backward":
                # Return messages before cursor
                end = idx
                start = max(0, end - limit)
                page = list(reversed(msgs[start:end]))
                next_cursor = msgs[start].sequence_number if start > 0 else None
            else:
                # Return messages after cursor
                start = idx + 1 if idx < len(msgs) and seq_nums[idx] == cursor else idx
                end = min(len(msgs), start + limit)
                page = msgs[start:end]
                next_cursor = msgs[end - 1].sequence_number if end < len(msgs) else None

        return (page, next_cursor)

    # -- Message operations --

    def edit_message(self, user_id: str, message_id: str, new_content: str) -> Message:
        msg = self.messages[message_id]
        if msg.sender_id != user_id:
            raise PermissionError("Only the sender can edit their message")
        msg.content = new_content
        msg.edited = True
        return msg

    def delete_message(self, user_id: str, message_id: str) -> Message:
        msg = self.messages[message_id]
        if msg.sender_id != user_id:
            raise PermissionError("Only the sender can delete their message")
        msg.content = "[deleted]"
        msg.deleted = True
        return msg

    # -- Typing indicators --

    def set_typing(self, user_id: str, conversation_id: str, current_time: float = None):
        current_time = current_time if current_time is not None else 0.0
        self.typing[(user_id, conversation_id)] = current_time

    def clear_typing(self, user_id: str, conversation_id: str):
        self.typing.pop((user_id, conversation_id), None)

    def get_typing_users(self, conversation_id: str, current_time: float = None) -> list[str]:
        result = []
        expiry = 5.0
        to_remove = []
        for (uid, cid), ts in self.typing.items():
            if cid == conversation_id:
                if current_time is not None and (current_time - ts) > expiry:
                    to_remove.append((uid, cid))
                else:
                    result.append(uid)
        for key in to_remove:
            del self.typing[key]
        return result

    # -- Search --

    def search_messages(self, conversation_id: str, query: str) -> list[Message]:
        conv = self.conversations.get(conversation_id)
        if not conv:
            return []
        query_lower = query.lower()
        return [m for m in conv.messages if not m.deleted and query_lower in m.content.lower()]

    # -- Conversations --

    def get_conversations(self, user_id: str) -> list[Conversation]:
        conv_ids = self.user_conversations.get(user_id, set())
        return [self.conversations[cid] for cid in conv_ids if cid in self.conversations]
