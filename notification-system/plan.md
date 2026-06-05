# Plan (Iteration 1)

Task: NOTIFICATION SYSTEM
System Design Interview Vol 1 - Chapter 10

OVERVIEW
--------
Implement a notification system that supports multiple delivery channels (push,
SMS, email) with priority queues, per-user rate limiting, template rendering,
retry with exponential backoff, and delivery tracking. The system is a
single-process Python application where delivery channels are simulated classes
that record what would be sent rather than actually sending.

The system models the full lifecycle: notification creation, template rendering,
channel routing, rate limiting, queuing by priority, delivery attempt with
simulated success/failure, retry on failure, and delivery status tracking.

REQUIREMENTS
------------
1.  Implement a NotificationService as the main entry point for sending notifications.
2.  Support three delivery channels, each as a simulated class:
    - PushChannel: simulates sending push notifications (payload: title, body, data)
    - SMSChannel: simulates sending SMS (payload: phone_number, message text, max 160 chars)
    - EmailChannel: simulates sending emails (payload: to, subject, body_html)
    Each channel has a configurable failure_rate (0.0-1.0) for testing retries.
3.  Implement a priority queue system with at least 3 priority levels:
    - CRITICAL (0): processed immediately (e.g., security alerts)
    - HIGH (1): processed before normal
    - NORMAL (2): standard notifications
    - LOW (3): processed last (e.g., marketing)
    Use heapq for the priority queue, ordered by (priority, timestamp).
4.  Implement per-user rate limiting:
    - Configurable max notifications per channel per time window per user.
    - Default: max 3 push per minute, 1 SMS per minute, 5 email per hour per user.
    - Notifications that exceed limits are dropped with a logged reason.
5.  Implement template rendering:
    - Templates are strings with {{variable}} placeholders.
    - A TemplateRegistry stores named templates.
    - Rendering substitutes variables from a context dict.
    - Example: "Hello {{name}}, your order {{order_id}} is ready."
6.  Implement retry with exponential backoff:
    - On delivery failure, retry up to max_retries times (default 3).
    - Delay between retries: base_delay * 2^attempt (e.g., 1s, 2s, 4s).
    - Add jitter: random factor between 0.5x and 1.5x of computed delay.
    - Track retry count per notification.
7.  Implement delivery tracking:
    - Each notification has a unique ID and status: PENDING, QUEUED, SENDING,
      DELIVERED, FAILED, RATE_LIMITED.
    - Track status transitions with timestamps.
    - Query delivery status by notification ID.
    - Query delivery history by user_id.
8.  Implement user preferences:
    - Users can opt out of specific channels.
    - Users can set quiet hours (no notifications between e.g., 22:00-08:00).
    - Users can set preferred channels ordered by preference.
9.  Implement notification grouping/batching:
    - Multiple notifications of the same type to the same user within a time
      window can be collapsed into one (e.g., "You have 5 new messages").
10. Support scheduling: notifications can be scheduled for future delivery
    (deliver_at timestamp).

DATA MODELS
-----------
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Optional
import heapq

class Priority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3

class Channel(Enum):
    PUSH = "push"
    SMS = "sms"
    EMAIL = "email"

class DeliveryStatus(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"

@dataclass
class Notification:
    id: str
    user_id: str
    channel: Channel
    priority: Priority
    template_name: Optional[str] = None
    template_context: dict = field(default_factory=dict)
    raw_content: Optional[dict] = None  # direct content (no template)
    status: DeliveryStatus = DeliveryStatus.PENDING
    created_at: float = 0.0
    deliver_at: Optional[float] = None  # scheduled delivery
    retry_count: int = 0
    max_retries: int = 3
    status_history: list[tuple[DeliveryStatus, float]] = field(default_factory=list)
    group_key: Optional[str] = None  # for batching

@dataclass
class UserPreferences:
    user_id: str
    opted_out_channels: set[Channel] = field(default_factory=set)
    quiet_hours: Optional[tuple[int, int]] = None  # (start_hour, end_hour) in 24h
    preferred_channels: list[Channel] = field(default_factory=lambda: [Channel.PUSH, Channel.EMAIL, Channel.SMS])

class DeliveryChannel:
    """Base class for delivery channels."""
    def __init__(self, failure_rate: float = 0.0): ...
    def send(self, notification: Notification, rendered_content: dict) -> bool: ...
    def get_sent_log(self) -> list[dict]: ...

class PushChannel(DeliveryChannel): ...
class SMSChannel(DeliveryChannel): ...
class EmailChannel(DeliveryChannel): ...

class TemplateRegistry:
    def register(self, name: str, template: str, channel: Channel): ...
    def render(self, name: str, context: dict, channel: Channel) -> str: ...

class NotificationService:
    def __init__(self, channels: dict[Channel, DeliveryChannel] = None,
                 rate_limits: dict[Channel, tuple[int, float]] = None): ...
    def send(self, notification: Notification, current_time: float = None) -> str: ...
    def send_batch(self, notifications: list[Notification], current_time: float = None) -> list[str]: ...
    def process_queue(self, current_time: float = None) -> int: ...
    def get_status(self, notification_id: str) -> DeliveryStatus: ...
    def get_user_history(self, user_id: str) -> list[Notification]: ...
    def set_user_preferences(self, prefs: UserPreferences): ...
    def register_template(self, name: str, template: str, channel: Channel): ...
    def get_stats(self) -> dict: ...

API SPECIFICATION
-----------------
# Setup
push = PushChannel(failure_rate=0.1)
sms = SMSChannel(failure_rate=0.05)
email = EmailChannel(failure_rate=0.02)

service = NotificationService(
    channels={Channel.PUSH: push, Channel.SMS: sms, Channel.EMAIL: email},
    rate_limits={
        Channel.PUSH: (3, 60.0),    # 3 per 60 seconds
        Channel.SMS: (1, 60.0),     # 1 per 60 seconds
        Channel.EMAIL: (5, 3600.0), # 5 per hour
    }
)

# Register templates
service.register_template("order_ready", "Hello {{name}}, order #{{order_id}} is ready!", Channel.PUSH)
service.register_template("order_ready", "Your order #{{order_id}} is ready for pickup.", Channel.SMS)

# Send notification
notif_id = service.send(Notification(
    id="n1",
    user_id="user_123",
    channel=Channel.PUSH,
    priority=Priority.HIGH,
    template_name="order_ready",
    template_context={"name": "Alice", "order_id": "456"},
    current_time=1000.0
))

# Process queue (delivers queued notifications)
delivered = service.process_queue(current_time=1000.0)

# Check status
status = service.get_status("n1")  # DeliveryStatus.DELIVERED

# User preferences
service.set_user_preferences(UserPreferences(
    user_id="user_123",
    opted_out_channels={Channel.SMS},
    quiet_hours=(22, 8)
))

# Get delivery history
history = service.get_user_history("user_123")

# Stats
stats = service.get_stats()
# {"total_sent": 1, "total_failed": 0, "total_rate_limited": 0, ...}

EXAMPLE USAGE WITH ASSERTIONS
------------------------------
# Basic send and deliver
service = NotificationService(
    channels={Channel.PUSH: PushChannel(failure_rate=0.0)}  # never fails
)
service.register_template("welcome", "Welcome {{name}}!", Channel.PUSH)

nid = service.send(Notification(
    id="test1",
    user_id="u1",
    channel=Channel.PUSH,
    priority=Priority.NORMAL,
    template_name="welcome",
    template_context={"name": "Bob"}
), current_time=1000.0)

service.process_queue(current_time=1000.0)
assert service.get_status("test1") == DeliveryStatus.DELIVERED

# Rate limiting
service2 = NotificationService(
    channels={Channel.SMS: SMSChannel(failure_rate=0.0)},
    rate_limits={Channel.SMS: (1, 60.0)}  # 1 per minute
)

service2.send(Notification(id="s1", user_id="u1", channel=Channel.SMS, priority=Priority.NORMAL,
                            raw_content={"message": "Hello"}), current_time=1000.0)
service2.process_queue(current_time=1000.0)
assert service2.get_status("s1") == DeliveryStatus.DELIVERED

service2.send(Notification(id="s2", user_id="u1", channel=Channel.SMS, priority=Priority.NORMAL,
                            raw_content={"message": "Again"}), current_time=1010.0)
service2.process_queue(current_time=1010.0)
assert service2.get_status("s2") == DeliveryStatus.RATE_LIMITED

# Priority ordering
service3 = NotificationService(
    channels={Channel.PUSH: PushChannel(failure_rate=0.0)}
)
service3.send(Notification(id="low", user_id="u1", channel=Channel.PUSH,
                            priority=Priority.LOW, raw_content={"msg": "low"}), current_time=100.0)
service3.send(Notification(id="critical", user_id="u1", channel=Channel.PUSH,
                            priority=Priority.CRITICAL, raw_content={"msg": "critical"}), current_time=100.0)
service3.process_queue(current_time=100.0)
# Both delivered, but critical was processed first
push_log = service3.channels[Channel.PUSH].get_sent_log()
assert push_log[0]["notification_id"] == "critical"

# Opt-out respected
service4 = NotificationService(channels={Channel.SMS: SMSChannel()})
service4.set_user_preferences(UserPreferences(user_id="u2", opted_out_channels={Channel.SMS}))
service4.send(Notification(id="opt1", user_id="u2", channel=Channel.SMS,
                            priority=Priority.NORMAL, raw_content={"msg": "hi"}), current_time=100.0)
service4.process_queue(current_time=100.0)
assert service4.get_status("opt1") != DeliveryStatus.DELIVERED

CONSTRAINTS
-----------
- All delivery is simulated (channels log what would be sent)
- Priority queue using heapq
- Rate limiting uses in-memory sliding window per user per channel
- Template rendering is simple string substitution (no Jinja2)
- Retry delays are simulated via timestamps, not actual sleep
- No external dependencies beyond Python standard library
- Target: 300-450 lines of code

TESTING REQUIREMENTS
--------------------
Write tests in test_notification_system.py using pytest. Include these test cases:

1.  Notification is delivered successfully with 0% failure rate
2.  Template rendering substitutes variables correctly
3.  Template with missing variable raises appropriate error
4.  Priority queue processes CRITICAL before LOW
5.  Rate limiting blocks excess notifications for same user/channel
6.  Rate limiting allows notifications after window expires
7.  Retry on failure retries up to max_retries times
8.  Exponential backoff delay increases with each retry
9.  User opt-out prevents delivery on opted-out channel
10. Quiet hours prevent delivery during configured hours
11. Delivery status transitions are tracked correctly
12. User history returns all notifications for a user
13. Scheduled notification is not delivered before deliver_at time
14. SMS content is truncated or validated at 160 characters
15. Stats correctly count delivered, failed, and rate-limited notifications

IMPORTANT - EFFORT LEVEL: MINIMAL
Keep plan VERY brief (2-3 paragraphs max). Focus only on algorithm choice. Skip architectural discussions and detailed analysis.

Plan written to `plan.md`. 

**Summary:** Single-file Python module using the provided data models. `heapq` priority queue, sliding-window rate limiter, regex template rendering, simulated channels with configurable failure rates, and retry via computed `deliver_at` timestamps (no real sleeping). All 15 test cases from the spec should be straightforward to implement against this design.

[Committed changes to planner branch]