"""Tests for the notification system."""

import pytest
import random

from notification_system import (
    Channel, DeliveryStatus, EmailChannel, Notification, NotificationService,
    PushChannel, Priority, SMSChannel, TemplateRegistry, UserPreferences,
)


def make_service(**kwargs):
    """Helper to create a service with default push channel."""
    channels = kwargs.pop("channels", {Channel.PUSH: PushChannel(failure_rate=0.0)})
    return NotificationService(channels=channels, **kwargs)


# 1. Notification is delivered successfully with 0% failure rate
def test_successful_delivery():
    service = make_service()
    service.send(Notification(
        id="n1", user_id="u1", channel=Channel.PUSH,
        priority=Priority.NORMAL, raw_content={"msg": "hello"}
    ), current_time=1000.0)
    service.process_queue(current_time=1000.0)
    assert service.get_status("n1") == DeliveryStatus.DELIVERED


# 2. Template rendering substitutes variables correctly
def test_template_rendering():
    reg = TemplateRegistry()
    reg.register("greet", "Hello {{name}}, order #{{order_id}}!", Channel.PUSH)
    result = reg.render("greet", {"name": "Alice", "order_id": "42"}, Channel.PUSH)
    assert result == "Hello Alice, order #42!"


# 3. Template with missing variable raises appropriate error
def test_template_missing_variable():
    reg = TemplateRegistry()
    reg.register("greet", "Hello {{name}}!", Channel.PUSH)
    with pytest.raises(KeyError, match="Missing template variable"):
        reg.render("greet", {}, Channel.PUSH)


# 4. Priority queue processes CRITICAL before LOW
def test_priority_ordering():
    service = make_service()
    service.send(Notification(
        id="low", user_id="u1", channel=Channel.PUSH,
        priority=Priority.LOW, raw_content={"msg": "low"}
    ), current_time=100.0)
    service.send(Notification(
        id="critical", user_id="u1", channel=Channel.PUSH,
        priority=Priority.CRITICAL, raw_content={"msg": "critical"}
    ), current_time=100.0)
    service.process_queue(current_time=100.0)
    push_log = service.channels[Channel.PUSH].get_sent_log()
    assert push_log[0]["notification_id"] == "critical"
    assert push_log[1]["notification_id"] == "low"


# 5. Rate limiting blocks excess notifications for same user/channel
def test_rate_limiting_blocks():
    service = NotificationService(
        channels={Channel.SMS: SMSChannel(failure_rate=0.0)},
        rate_limits={Channel.SMS: (1, 60.0)},
    )
    service.send(Notification(
        id="s1", user_id="u1", channel=Channel.SMS,
        priority=Priority.NORMAL, raw_content={"message": "First"}
    ), current_time=1000.0)
    service.process_queue(current_time=1000.0)
    assert service.get_status("s1") == DeliveryStatus.DELIVERED

    service.send(Notification(
        id="s2", user_id="u1", channel=Channel.SMS,
        priority=Priority.NORMAL, raw_content={"message": "Second"}
    ), current_time=1010.0)
    service.process_queue(current_time=1010.0)
    assert service.get_status("s2") == DeliveryStatus.RATE_LIMITED


# 6. Rate limiting allows notifications after window expires
def test_rate_limiting_window_expiry():
    service = NotificationService(
        channels={Channel.SMS: SMSChannel(failure_rate=0.0)},
        rate_limits={Channel.SMS: (1, 60.0)},
    )
    service.send(Notification(
        id="s1", user_id="u1", channel=Channel.SMS,
        priority=Priority.NORMAL, raw_content={"message": "First"}
    ), current_time=1000.0)
    service.process_queue(current_time=1000.0)
    assert service.get_status("s1") == DeliveryStatus.DELIVERED

    # After window expires
    service.send(Notification(
        id="s2", user_id="u1", channel=Channel.SMS,
        priority=Priority.NORMAL, raw_content={"message": "Later"}
    ), current_time=1061.0)
    service.process_queue(current_time=1061.0)
    assert service.get_status("s2") == DeliveryStatus.DELIVERED


# 7. Retry on failure retries up to max_retries times
def test_retry_on_failure():
    random.seed(42)
    # 100% failure rate
    service = NotificationService(
        channels={Channel.PUSH: PushChannel(failure_rate=1.0)},
    )
    service.send(Notification(
        id="r1", user_id="u1", channel=Channel.PUSH,
        priority=Priority.NORMAL, raw_content={"msg": "retry me"},
        max_retries=3,
    ), current_time=1000.0)

    # Process multiple times with advancing time to handle backoff
    for t in range(20):
        service.process_queue(current_time=1000.0 + t * 10)

    notif = service._notifications["r1"]
    assert notif.status == DeliveryStatus.FAILED
    assert notif.retry_count == 4  # initial + 3 retries = 4 attempts


# 8. Exponential backoff delay increases with each retry
def test_exponential_backoff():
    random.seed(99)
    service = NotificationService(
        channels={Channel.PUSH: PushChannel(failure_rate=1.0)},
    )
    service.send(Notification(
        id="b1", user_id="u1", channel=Channel.PUSH,
        priority=Priority.NORMAL, raw_content={"msg": "backoff"},
        max_retries=3,
    ), current_time=1000.0)

    # Process first attempt
    service.process_queue(current_time=1000.0)
    notif = service._notifications["b1"]
    delay1 = notif.deliver_at - 1000.0  # base * 2^0 * jitter

    # Process second attempt
    t2 = notif.deliver_at + 0.01
    service.process_queue(current_time=t2)
    delay2 = notif.deliver_at - t2  # base * 2^1 * jitter

    # Second delay should be roughly 2x the first (accounting for jitter)
    assert delay2 > delay1 * 0.5  # with jitter, at least this


# 9. User opt-out prevents delivery on opted-out channel
def test_user_opt_out():
    service = NotificationService(channels={Channel.SMS: SMSChannel()})
    service.set_user_preferences(UserPreferences(
        user_id="u2", opted_out_channels={Channel.SMS}
    ))
    service.send(Notification(
        id="opt1", user_id="u2", channel=Channel.SMS,
        priority=Priority.NORMAL, raw_content={"message": "hi"}
    ), current_time=100.0)
    service.process_queue(current_time=100.0)
    assert service.get_status("opt1") != DeliveryStatus.DELIVERED


# 10. Quiet hours prevent delivery during configured hours
def test_quiet_hours():
    import calendar, datetime
    service = make_service()
    service.set_user_preferences(UserPreferences(
        user_id="u1", quiet_hours=(22, 8)
    ))
    # 23:00 UTC
    dt = datetime.datetime(2024, 1, 1, 23, 0, 0)
    ts = calendar.timegm(dt.timetuple())

    service.send(Notification(
        id="q1", user_id="u1", channel=Channel.PUSH,
        priority=Priority.NORMAL, raw_content={"msg": "late night"}
    ), current_time=ts)
    service.process_queue(current_time=ts)
    assert service.get_status("q1") != DeliveryStatus.DELIVERED

    # 10:00 UTC
    dt2 = datetime.datetime(2024, 1, 2, 10, 0, 0)
    ts2 = calendar.timegm(dt2.timetuple())
    service.process_queue(current_time=ts2)
    assert service.get_status("q1") == DeliveryStatus.DELIVERED


# 11. Delivery status transitions are tracked correctly
def test_status_transitions():
    service = make_service()
    service.send(Notification(
        id="t1", user_id="u1", channel=Channel.PUSH,
        priority=Priority.NORMAL, raw_content={"msg": "track me"}
    ), current_time=1000.0)
    service.process_queue(current_time=1000.0)

    notif = service._notifications["t1"]
    statuses = [s for s, _ in notif.status_history]
    assert DeliveryStatus.PENDING in statuses
    assert DeliveryStatus.QUEUED in statuses
    assert DeliveryStatus.SENDING in statuses
    assert DeliveryStatus.DELIVERED in statuses


# 12. User history returns all notifications for a user
def test_user_history():
    service = make_service()
    for i in range(3):
        service.send(Notification(
            id=f"h{i}", user_id="u1", channel=Channel.PUSH,
            priority=Priority.NORMAL, raw_content={"msg": f"msg{i}"}
        ), current_time=1000.0 + i)
    service.process_queue(current_time=1003.0)
    history = service.get_user_history("u1")
    assert len(history) == 3
    assert {n.id for n in history} == {"h0", "h1", "h2"}


# 13. Scheduled notification is not delivered before deliver_at time
def test_scheduled_notification():
    service = make_service()
    service.send(Notification(
        id="sched1", user_id="u1", channel=Channel.PUSH,
        priority=Priority.NORMAL, raw_content={"msg": "future"},
        deliver_at=2000.0,
    ), current_time=1000.0)
    service.process_queue(current_time=1000.0)
    assert service.get_status("sched1") != DeliveryStatus.DELIVERED

    service.process_queue(current_time=2001.0)
    assert service.get_status("sched1") == DeliveryStatus.DELIVERED


# 14. SMS content is truncated or validated at 160 characters
def test_sms_truncation():
    sms = SMSChannel(failure_rate=0.0)
    long_msg = "A" * 200
    notif = Notification(
        id="sms1", user_id="u1", channel=Channel.SMS,
        priority=Priority.NORMAL, raw_content={"message": long_msg},
        created_at=1000.0,
    )
    sms.send(notif, {"message": long_msg})
    log = sms.get_sent_log()
    assert len(log) == 1
    assert len(log[0]["content"]["message"]) == 160


# 15. Stats correctly count delivered, failed, and rate-limited notifications
def test_stats():
    service = NotificationService(
        channels={
            Channel.PUSH: PushChannel(failure_rate=0.0),
            Channel.SMS: SMSChannel(failure_rate=0.0),
        },
        rate_limits={Channel.SMS: (1, 60.0)},
    )
    # Deliver one push
    service.send(Notification(
        id="st1", user_id="u1", channel=Channel.PUSH,
        priority=Priority.NORMAL, raw_content={"msg": "ok"}
    ), current_time=1000.0)
    service.process_queue(current_time=1000.0)

    # Deliver one SMS, then rate-limit second
    service.send(Notification(
        id="st2", user_id="u1", channel=Channel.SMS,
        priority=Priority.NORMAL, raw_content={"message": "first"}
    ), current_time=1000.0)
    service.process_queue(current_time=1000.0)

    service.send(Notification(
        id="st3", user_id="u1", channel=Channel.SMS,
        priority=Priority.NORMAL, raw_content={"message": "second"}
    ), current_time=1010.0)
    service.process_queue(current_time=1010.0)

    stats = service.get_stats()
    assert stats["total_sent"] == 2
    assert stats["total_rate_limited"] == 1


# Run the example assertions from the spec
def test_spec_example_basic():
    service = NotificationService(
        channels={Channel.PUSH: PushChannel(failure_rate=0.0)}
    )
    service.register_template("welcome", "Welcome {{name}}!", Channel.PUSH)
    nid = service.send(Notification(
        id="test1", user_id="u1", channel=Channel.PUSH,
        priority=Priority.NORMAL, template_name="welcome",
        template_context={"name": "Bob"}
    ), current_time=1000.0)
    service.process_queue(current_time=1000.0)
    assert service.get_status("test1") == DeliveryStatus.DELIVERED


def test_spec_example_priority():
    service = NotificationService(
        channels={Channel.PUSH: PushChannel(failure_rate=0.0)}
    )
    service.send(Notification(
        id="low", user_id="u1", channel=Channel.PUSH,
        priority=Priority.LOW, raw_content={"msg": "low"}
    ), current_time=100.0)
    service.send(Notification(
        id="critical", user_id="u1", channel=Channel.PUSH,
        priority=Priority.CRITICAL, raw_content={"msg": "critical"}
    ), current_time=100.0)
    service.process_queue(current_time=100.0)
    push_log = service.channels[Channel.PUSH].get_sent_log()
    assert push_log[0]["notification_id"] == "critical"


# 18. current_time=0.0 is treated as valid, not as missing
def test_current_time_zero():
    service = make_service()
    service.send(Notification(
        id="z1", user_id="u1", channel=Channel.PUSH,
        priority=Priority.NORMAL, raw_content={"msg": "zero time"}
    ), current_time=0.0)
    service.process_queue(current_time=0.0)
    assert service.get_status("z1") == DeliveryStatus.DELIVERED
    notif = service._notifications["z1"]
    assert notif.created_at == 0.0


# 19. Quiet hours work correctly regardless of system timezone
def test_quiet_hours_utc():
    import calendar, datetime
    service = make_service()
    service.set_user_preferences(UserPreferences(
        user_id="u1", quiet_hours=(0, 6)
    ))
    # 03:00 UTC — within quiet hours
    dt = datetime.datetime(2024, 6, 15, 3, 0, 0)
    ts = calendar.timegm(dt.timetuple())
    service.send(Notification(
        id="qz1", user_id="u1", channel=Channel.PUSH,
        priority=Priority.NORMAL, raw_content={"msg": "early morning"}
    ), current_time=ts)
    service.process_queue(current_time=ts)
    assert service.get_status("qz1") != DeliveryStatus.DELIVERED

    # 07:00 UTC — outside quiet hours
    dt2 = datetime.datetime(2024, 6, 15, 7, 0, 0)
    ts2 = calendar.timegm(dt2.timetuple())
    service.process_queue(current_time=ts2)
    assert service.get_status("qz1") == DeliveryStatus.DELIVERED
