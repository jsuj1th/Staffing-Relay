from django.db import models


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
