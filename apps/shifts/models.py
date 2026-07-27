from django.conf import settings
from django.db import models


class Shift(models.Model):
    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="shifts",
    )
    # Where this shift is worked. Needed on the shift itself: shared staff
    # (management, floaters) have no home location and are linked to several,
    # so the employee record can't say which site a given day belongs to.
    location = models.ForeignKey(
        "locations.Location",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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

    def overlapping(self):
        """This employee's other shifts that clash in time on the same day.
        Half-open comparison: 9–12 and 12–5 are back-to-back, not a clash."""
        return Shift.objects.filter(
            employee_id=self.employee_id,
            date=self.date,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        ).exclude(pk=self.pk)

    def save(self, *args, **kwargs):
        """Double-bookings are flagged, not blocked — a manager may genuinely
        want one. Both sides go yellow so the clash is visible on the schedule.
        ponytail: flagging reuses needs_attention rather than adding a separate
        conflict field; split them if attention ever needs its own meaning."""
        fields = set(kwargs.get("update_fields") or ())
        # The confirm/flag buttons must stay able to clear the flag.
        just_toggling = bool(fields) and fields <= {"confirmed", "needs_attention"}
        clashes = None
        if not just_toggling and self.employee_id and self.date and self.start_time and self.end_time:
            clashes = self.overlapping()
            if clashes.exists():
                self.needs_attention = True
                if fields:
                    kwargs["update_fields"] = fields | {"needs_attention"}
            else:
                clashes = None

        super().save(*args, **kwargs)

        if clashes is not None:
            clashes.update(needs_attention=True)

    @property
    def site(self):
        """Location this shift belongs to. Falls back to the employee's home
        location, then their first linked one, for shifts created before
        location was recorded per shift."""
        if self.location_id:
            return self.location
        if self.employee.location_id:
            return self.employee.location
        link = self.employee.employee_locations.first()
        return link.location if link else None

    @property
    def compact_time(self):
        """12-hour, minutes only when non-zero, e.g. 09:00-16:00 -> '9-4'."""
        def h(t):
            hr = t.hour % 12 or 12
            return f"{hr}:{t.minute:02d}" if t.minute else f"{hr}"
        return f"{h(self.start_time)}-{h(self.end_time)}"
