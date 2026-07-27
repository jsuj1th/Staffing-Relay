from django.db import models
from django.utils import timezone


class NotificationSetting(models.Model):
    """Global notification switches. Singleton row (pk=1)."""
    # Gates ALL employee shift texts: assignments, removals and changes.
    # Manual per-shift reminders deliberately bypass it.
    shift_sms_enabled = models.BooleanField(default=True)
    # Master switch for leave alerts to the admin contacts below.
    leave_alerts_enabled = models.BooleanField(default=True)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class AdminContact(models.Model):
    """A person (office manager, owner, …) alerted about employee leave activity,
    on the channel they picked."""
    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email only"
        SMS = "SMS", "SMS only"
        BOTH = "BOTH", "Email and SMS"

    name = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=120, blank=True, help_text="e.g. Office Manager")
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.EMAIL)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_channel_display()})"

    @property
    def wants_email(self):
        return bool(self.email) and self.channel in (self.Channel.EMAIL, self.Channel.BOTH)

    @property
    def wants_sms(self):
        return bool(self.phone) and self.channel in (self.Channel.SMS, self.Channel.BOTH)


class SmsLog(models.Model):
    from_phone = models.CharField(max_length=20)
    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sms_logs",
    )
    inbound_msg = models.TextField()
    outbound_msg = models.TextField(blank=True)
    leave = models.ForeignKey(
        "leaves.Leave",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sms_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"SMS from {self.from_phone} at {self.created_at:%Y-%m-%d %H:%M}"


class NotificationQueue(models.Model):
    """Queue for batched SMS notifications (shift assignments, leave updates, etc)."""
    class NotificationType(models.TextChoices):
        SHIFT_ASSIGNED = "SHIFT_ASSIGNED", "Shift Assigned"
        SHIFT_CANCELLED = "SHIFT_CANCELLED", "Shift Cancelled"
        SHIFT_UPDATED = "SHIFT_UPDATED", "Shift Updated"
        LEAVE_APPROVED = "LEAVE_APPROVED", "Leave Approved"
        LEAVE_REJECTED = "LEAVE_REJECTED", "Leave Rejected"
        LEAVE_CANCELLED = "LEAVE_CANCELLED", "Leave Cancelled"

    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="notification_queue",
    )
    notification_type = models.CharField(
        max_length=20,
        choices=NotificationType.choices,
    )
    message_body = models.TextField()
    related_object_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="ID of related Shift or Leave",
    )
    is_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    scheduled_send_at = models.DateTimeField(
        default=timezone.now,
        help_text="When this notification should be sent (for batching)",
    )

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["employee", "is_sent", "created_at"]),
        ]

    def __str__(self):
        status = "✓" if self.is_sent else "⧖"
        return f"{status} {self.employee.name} - {self.get_notification_type_display()}"
