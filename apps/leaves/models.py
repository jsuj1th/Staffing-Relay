from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Leave(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        EXTREME = "EXTREME", "Approved (Extreme Coverage)"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="leaves",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    # Snapshot of ratio at time of decision (internal — never shown to employee via SMS)
    ratio_before = models.JSONField(null=True, blank=True)
    ratio_after = models.JSONField(null=True, blank=True)
    # Human-readable rejection reason (internal, shown only on dashboard)
    internal_note = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Null means auto-processed via SMS",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.employee.name}: {self.start_date} – {self.end_date} [{self.status}]"

    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1
