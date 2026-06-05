"""Notification system with multi-channel delivery, priority queues, rate limiting, and retry."""

import datetime
import heapq
import random
import re
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Optional


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
    raw_content: Optional[dict] = None
    status: DeliveryStatus = DeliveryStatus.PENDING
    created_at: float = 0.0
    deliver_at: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    status_history: list[tuple[DeliveryStatus, float]] = field(default_factory=list)
    group_key: Optional[str] = None


@dataclass
class UserPreferences:
    user_id: str
    opted_out_channels: set[Channel] = field(default_factory=set)
    quiet_hours: Optional[tuple[int, int]] = None
    preferred_channels: list[Channel] = field(default_factory=lambda: [Channel.PUSH, Channel.EMAIL, Channel.SMS])


class DeliveryChannel:
    """Base class for simulated delivery channels."""

    def __init__(self, failure_rate: float = 0.0):
        self.failure_rate = failure_rate
        self._sent_log: list[dict] = []

    def send(self, notification: Notification, rendered_content: dict) -> bool:
        success = random.random() >= self.failure_rate
        if success:
            self._sent_log.append({
                "notification_id": notification.id,
                "user_id": notification.user_id,
                "content": rendered_content,
                "timestamp": notification.created_at,
            })
        return success

    def get_sent_log(self) -> list[dict]:
        return list(self._sent_log)


class PushChannel(DeliveryChannel):
    """Simulates push notifications."""

    def send(self, notification: Notification, rendered_content: dict) -> bool:
        success = random.random() >= self.failure_rate
        if success:
            self._sent_log.append({
                "notification_id": notification.id,
                "user_id": notification.user_id,
                "content": rendered_content,
                "channel": "push",
                "timestamp": notification.created_at,
            })
        return success


class SMSChannel(DeliveryChannel):
    """Simulates SMS delivery. Truncates messages to 160 chars."""

    def send(self, notification: Notification, rendered_content: dict) -> bool:
        if "message" in rendered_content and len(rendered_content["message"]) > 160:
            rendered_content = dict(rendered_content)
            rendered_content["message"] = rendered_content["message"][:160]
        success = random.random() >= self.failure_rate
        if success:
            self._sent_log.append({
                "notification_id": notification.id,
                "user_id": notification.user_id,
                "content": rendered_content,
                "channel": "sms",
                "timestamp": notification.created_at,
            })
        return success


class EmailChannel(DeliveryChannel):
    """Simulates email delivery."""

    def send(self, notification: Notification, rendered_content: dict) -> bool:
        success = random.random() >= self.failure_rate
        if success:
            self._sent_log.append({
                "notification_id": notification.id,
                "user_id": notification.user_id,
                "content": rendered_content,
                "channel": "email",
                "timestamp": notification.created_at,
            })
        return success


class TemplateRegistry:
    """Stores and renders named templates per channel."""

    def __init__(self):
        self._templates: dict[tuple[str, Channel], str] = {}

    def register(self, name: str, template: str, channel: Channel):
        self._templates[(name, channel)] = template

    def render(self, name: str, context: dict, channel: Channel) -> str:
        key = (name, channel)
        if key not in self._templates:
            raise KeyError(f"Template '{name}' not found for channel {channel.value}")
        template = self._templates[key]

        def replace_var(match):
            var = match.group(1)
            if var not in context:
                raise KeyError(f"Missing template variable: '{var}'")
            return str(context[var])

        return re.sub(r"\{\{(\w+)\}\}", replace_var, template)


class RateLimiter:
    """Sliding window rate limiter per user per channel."""

    def __init__(self, limits: dict[Channel, tuple[int, float]]):
        self._limits = limits
        self._windows: dict[tuple[str, Channel], deque] = defaultdict(deque)

    def check(self, user_id: str, channel: Channel, current_time: float) -> bool:
        if channel not in self._limits:
            return True
        max_count, window_size = self._limits[channel]
        key = (user_id, channel)
        q = self._windows[key]
        while q and q[0] <= current_time - window_size:
            q.popleft()
        return len(q) < max_count

    def record(self, user_id: str, channel: Channel, current_time: float):
        key = (user_id, channel)
        self._windows[key].append(current_time)


class NotificationService:
    """Main entry point for sending and processing notifications."""

    def __init__(self, channels: dict[Channel, DeliveryChannel] = None,
                 rate_limits: dict[Channel, tuple[int, float]] = None):
        self.channels = channels or {}
        self._rate_limiter = RateLimiter(rate_limits or {
            Channel.PUSH: (3, 60.0),
            Channel.SMS: (1, 60.0),
            Channel.EMAIL: (5, 3600.0),
        })
        self._template_registry = TemplateRegistry()
        self._queue: list[tuple] = []  # heapq of (priority, timestamp, notification)
        self._notifications: dict[str, Notification] = {}
        self._user_prefs: dict[str, UserPreferences] = {}
        self._pending_groups: dict[tuple[str, str], list[Notification]] = defaultdict(list)
        self._group_window = 5.0  # seconds to batch same group_key
        self._stats = {"total_sent": 0, "total_failed": 0, "total_rate_limited": 0}
        self._seq = 0  # tie-breaker for heapq

    def _update_status(self, notif: Notification, status: DeliveryStatus, current_time: float):
        notif.status = status
        notif.status_history.append((status, current_time))

    def register_template(self, name: str, template: str, channel: Channel):
        self._template_registry.register(name, template, channel)

    def set_user_preferences(self, prefs: UserPreferences):
        self._user_prefs[prefs.user_id] = prefs

    def send(self, notification: Notification, current_time: float = None) -> str:
        """Enqueue a notification for delivery."""
        current_time = current_time if current_time is not None else 0.0
        notification.created_at = current_time
        self._update_status(notification, DeliveryStatus.PENDING, current_time)

        # Check user opt-out
        prefs = self._user_prefs.get(notification.user_id)
        if prefs and notification.channel in prefs.opted_out_channels:
            self._update_status(notification, DeliveryStatus.RATE_LIMITED, current_time)
            self._notifications[notification.id] = notification
            return notification.id

        # Check rate limit
        if not self._rate_limiter.check(notification.user_id, notification.channel, current_time):
            self._update_status(notification, DeliveryStatus.RATE_LIMITED, current_time)
            self._stats["total_rate_limited"] += 1
            self._notifications[notification.id] = notification
            return notification.id

        self._update_status(notification, DeliveryStatus.QUEUED, current_time)
        self._notifications[notification.id] = notification
        self._seq += 1
        heapq.heappush(self._queue, (notification.priority, current_time, self._seq, notification))
        return notification.id

    def send_batch(self, notifications: list[Notification], current_time: float = None) -> list[str]:
        return [self.send(n, current_time) for n in notifications]

    def _is_quiet_hours(self, user_id: str, current_time: float) -> bool:
        prefs = self._user_prefs.get(user_id)
        if not prefs or not prefs.quiet_hours:
            return False
        start, end = prefs.quiet_hours
        hour = datetime.datetime.fromtimestamp(current_time, datetime.UTC).hour
        if start > end:  # overnight, e.g., 22-8
            return hour >= start or hour < end
        return start <= hour < end

    def _render_content(self, notification: Notification) -> dict:
        if notification.template_name:
            rendered = self._template_registry.render(
                notification.template_name, notification.template_context, notification.channel
            )
            return {"rendered": rendered}
        return dict(notification.raw_content or {})

    def process_queue(self, current_time: float = None) -> int:
        """Process all queued notifications. Returns count of delivered."""
        current_time = current_time if current_time is not None else 0.0
        delivered = 0
        deferred = []

        while self._queue:
            priority, ts, seq, notif = heapq.heappop(self._queue)

            # Skip if already terminal
            if notif.status in (DeliveryStatus.DELIVERED, DeliveryStatus.FAILED, DeliveryStatus.RATE_LIMITED):
                continue

            # Scheduled for future
            if notif.deliver_at and notif.deliver_at > current_time:
                deferred.append((priority, ts, seq, notif))
                continue

            # Quiet hours check
            if self._is_quiet_hours(notif.user_id, current_time):
                deferred.append((priority, ts, seq, notif))
                continue

            # Rate limit check at delivery time
            if not self._rate_limiter.check(notif.user_id, notif.channel, current_time):
                self._update_status(notif, DeliveryStatus.RATE_LIMITED, current_time)
                self._stats["total_rate_limited"] += 1
                continue

            channel = self.channels.get(notif.channel)
            if not channel:
                self._update_status(notif, DeliveryStatus.FAILED, current_time)
                self._stats["total_failed"] += 1
                continue

            self._update_status(notif, DeliveryStatus.SENDING, current_time)
            content = self._render_content(notif)
            success = channel.send(notif, content)

            if success:
                self._update_status(notif, DeliveryStatus.DELIVERED, current_time)
                self._rate_limiter.record(notif.user_id, notif.channel, current_time)
                self._stats["total_sent"] += 1
                delivered += 1
            else:
                notif.retry_count += 1
                if notif.retry_count <= notif.max_retries:
                    delay = 1.0 * (2 ** (notif.retry_count - 1))
                    jitter = random.uniform(0.5, 1.5)
                    notif.deliver_at = current_time + delay * jitter
                    self._update_status(notif, DeliveryStatus.QUEUED, current_time)
                    self._seq += 1
                    deferred.append((notif.priority, ts, self._seq, notif))
                else:
                    self._update_status(notif, DeliveryStatus.FAILED, current_time)
                    self._stats["total_failed"] += 1

        for item in deferred:
            heapq.heappush(self._queue, item)

        return delivered

    def get_status(self, notification_id: str) -> DeliveryStatus:
        notif = self._notifications.get(notification_id)
        if not notif:
            raise KeyError(f"Notification '{notification_id}' not found")
        return notif.status

    def get_user_history(self, user_id: str) -> list[Notification]:
        return [n for n in self._notifications.values() if n.user_id == user_id]

    def get_stats(self) -> dict:
        return dict(self._stats)
