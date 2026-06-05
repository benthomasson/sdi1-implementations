"""Tests for the chat system."""

import pytest
from chat_system import ChatServer, UserStatus, MessageType


@pytest.fixture
def server():
    return ChatServer(idle_timeout=300.0)


def test_send_receive_direct_message(server):
    """1. Send and receive 1:1 message between two connected users."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    msg = server.send_message("alice", "bob", "Hello Bob!", current_time=1.0)
    assert msg.sender_id == "alice"
    assert msg.content == "Hello Bob!"
    assert len(server.connections["bob"].inbox) == 1
    assert server.connections["bob"].inbox[0].message_id == msg.message_id


def test_monotonic_sequence_numbers(server):
    """2. Messages have monotonically increasing sequence numbers per conversation."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    m1 = server.send_message("alice", "bob", "First", current_time=1.0)
    m2 = server.send_message("alice", "bob", "Second", current_time=2.0)
    m3 = server.send_message("bob", "alice", "Third", current_time=3.0)
    assert m1.sequence_number == 1
    assert m2.sequence_number == 2
    assert m3.sequence_number == 3
    assert m1.sequence_number < m2.sequence_number < m3.sequence_number


def test_same_conversation_id(server):
    """3. Same 1:1 conversation ID regardless of who sends first."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    m1 = server.send_message("alice", "bob", "Hi", current_time=1.0)
    m2 = server.send_message("bob", "alice", "Hey", current_time=2.0)
    assert m1.conversation_id == m2.conversation_id


def test_group_creation_includes_all_members(server):
    """4. Group creation includes all specified members plus creator."""
    server.connect("alice", current_time=0.0)
    gid = server.create_group("alice", "Test Group", ["bob", "charlie"], current_time=0.0)
    info = server.get_group_info(gid)
    assert "alice" in info.members
    assert "bob" in info.members
    assert "charlie" in info.members
    assert info.creator_id == "alice"


def test_group_message_delivered_to_all_except_sender(server):
    """5. Group message delivered to all members except sender."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    server.connect("charlie", current_time=0.0)
    gid = server.create_group("alice", "Group", ["bob", "charlie"], current_time=0.0)
    server.send_group_message("alice", gid, "Hello group!", current_time=1.0)
    assert len(server.connections["bob"].inbox) == 1
    assert len(server.connections["charlie"].inbox) == 1
    assert len(server.connections["alice"].inbox) == 0


def test_read_receipts(server):
    """6. Read receipt marks messages as read, unread count updates correctly."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    m1 = server.send_message("alice", "bob", "Msg 1", current_time=1.0)
    m2 = server.send_message("alice", "bob", "Msg 2", current_time=2.0)
    assert server.get_unread_count("bob", m1.conversation_id) == 2
    server.mark_read("bob", m1.conversation_id, m1.message_id)
    assert server.get_unread_count("bob", m1.conversation_id) == 1
    server.mark_read("bob", m2.conversation_id, m2.message_id)
    assert server.get_unread_count("bob", m2.conversation_id) == 0


def test_offline_queue_on_reconnect(server):
    """7. Offline user receives messages in offline queue, flushed to inbox on reconnect."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    server.disconnect("bob", current_time=1.0)
    server.send_message("alice", "bob", "Are you there?", current_time=2.0)
    assert len(server.connections["bob"].offline_queue) == 1
    server.connect("bob", current_time=3.0)
    assert len(server.connections["bob"].offline_queue) == 0
    assert any(m.content == "Are you there?" for m in server.connections["bob"].inbox)


def test_status_transitions(server):
    """8. Online/offline/away status transitions correctly."""
    server.connect("alice", current_time=0.0)
    assert server.get_status("alice", current_time=0.0) == UserStatus.ONLINE
    server.disconnect("alice", current_time=1.0)
    assert server.get_status("alice") == UserStatus.OFFLINE
    server.connect("alice", current_time=2.0)
    assert server.get_status("alice", current_time=2.0) == UserStatus.ONLINE


def test_away_after_idle_timeout(server):
    """9. Away status triggers after idle timeout."""
    server.connect("alice", current_time=1000.0)
    server.heartbeat("alice", current_time=1000.0)
    assert server.get_status("alice", current_time=1100.0) == UserStatus.ONLINE
    assert server.get_status("alice", current_time=1500.0) == UserStatus.AWAY


def test_history_pagination(server):
    """10. Message history pagination returns correct pages."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    for i in range(25):
        server.send_message("alice", "bob", f"Message {i}", current_time=float(i))
    conv_id = server.conversations[list(server.conversations.keys())[0]].conversation_id
    msgs, cursor = server.get_history(conv_id, limit=10)
    assert len(msgs) == 10
    assert cursor is not None
    msgs2, cursor2 = server.get_history(conv_id, cursor=cursor, limit=10)
    assert len(msgs2) == 10


def test_backward_pagination_returns_older(server):
    """11. Cursor-based pagination: backward returns older messages."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    for i in range(10):
        server.send_message("alice", "bob", f"Msg {i}", current_time=float(i))
    conv_id = list(server.conversations.keys())[0]
    msgs, _ = server.get_history(conv_id, limit=5, direction="backward")
    # backward: newest first
    assert msgs[0].sequence_number > msgs[-1].sequence_number


def test_edit_message(server):
    """12. Edit message updates content and sets edited flag."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    msg = server.send_message("alice", "bob", "Original", current_time=1.0)
    edited = server.edit_message("alice", msg.message_id, "Edited content")
    assert edited.edited is True
    assert edited.content == "Edited content"


def test_delete_message(server):
    """13. Delete message soft-deletes (content replaced)."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    msg = server.send_message("alice", "bob", "To delete", current_time=1.0)
    deleted = server.delete_message("alice", msg.message_id)
    assert deleted.deleted is True
    assert deleted.content == "[deleted]"


def test_only_sender_can_edit_delete(server):
    """14. Only sender can edit/delete their own messages."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    msg = server.send_message("alice", "bob", "Alice's msg", current_time=1.0)
    with pytest.raises(PermissionError):
        server.edit_message("bob", msg.message_id, "Hacked!")
    with pytest.raises(PermissionError):
        server.delete_message("bob", msg.message_id)


def test_typing_indicators(server):
    """15. Typing indicators show/clear correctly."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    msg = server.send_message("alice", "bob", "Hi", current_time=1.0)
    conv_id = msg.conversation_id
    server.set_typing("alice", conv_id, current_time=10.0)
    assert "alice" in server.get_typing_users(conv_id, current_time=10.0)
    server.clear_typing("alice", conv_id)
    assert "alice" not in server.get_typing_users(conv_id, current_time=10.0)


def test_sender_unread_count_is_zero(server):
    """Sender's own messages don't count as unread for the sender."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    server.send_message("alice", "bob", "Hello", current_time=1.0)
    server.send_message("alice", "bob", "Hello again", current_time=2.0)
    conv_id = server.connections["bob"].inbox[0].conversation_id
    assert server.get_unread_count("alice", conv_id) == 0
    assert server.get_unread_count("bob", conv_id) == 2


def test_presence_notification_on_connect(server):
    """Contacts receive presence notification when a user comes online."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    server.send_message("alice", "bob", "Hi", current_time=1.0)
    alice_inbox_before = len(server.connections["alice"].inbox)
    server.disconnect("bob", current_time=2.0)
    server.connect("bob", current_time=3.0)
    new_msgs = server.connections["alice"].inbox[alice_inbox_before:]
    assert any("offline" in m.content for m in new_msgs)
    assert any("online" in m.content for m in new_msgs)


def test_get_conversations_uses_index(server):
    """get_conversations returns all conversations a user participates in."""
    server.connect("alice", current_time=0.0)
    server.connect("bob", current_time=0.0)
    server.connect("charlie", current_time=0.0)
    server.send_message("alice", "bob", "Hi bob", current_time=1.0)
    gid = server.create_group("alice", "Group", ["charlie"], current_time=2.0)
    convs = server.get_conversations("alice")
    assert len(convs) == 2
    conv_ids = {c.conversation_id for c in convs}
    assert gid in conv_ids
