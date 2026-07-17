from django.db import models
from django.utils import timezone


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
        LEAVE_APPROVED = "LEAVE_APPROVED", "Leave Approved"
        LEAVE_REJECTED = "LEAVE_REJECTED", "Leave Rejected"

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
