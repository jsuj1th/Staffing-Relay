from django.conf import settings
from django.db import models


class Shift(models.Model):
    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="shifts",
    )
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    # Combined-schedule status: unconfirmed (purple) -> confirmed (blue);
    # needs_attention highlights the entry (yellow).
    confirmed = models.BooleanField(default=False)
    needs_attention = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "start_time"]

    def __str__(self):
        return f"{self.employee.name} — {self.date} {self.start_time}-{self.end_time}"

    @property
    def compact_time(self):
        """12-hour, minutes only when non-zero, e.g. 09:00-16:00 -> '9-4'."""
        def h(t):
            hr = t.hour % 12 or 12
            return f"{hr}:{t.minute:02d}" if t.minute else f"{hr}"
        return f"{h(self.start_time)}-{h(self.end_time)}"
