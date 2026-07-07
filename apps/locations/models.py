from django.db import models


class Location(models.Model):
    name = models.CharField(max_length=200)
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state})"

    def get_ratio_today(self):
        from apps.leaves.ratio import get_active_counts
        from django.utils import timezone
        today = timezone.localdate()
        p, ma = get_active_counts(self.id, today, today)
        return p, ma

    def ratio_status(self):
        p, ma = self.get_ratio_today()
        if ma == 0:
            return "critical"
        if p * 2 > ma * 3:
            return "critical"
        if p > ma:
            return "warning"
        return "good"


class EmployeeLocation(models.Model):
    """Through model for FRONT_DESK / MANAGEMENT employees who serve multiple locations."""
    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="employee_locations",
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="shared_employee_locations",
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        unique_together = [("employee", "location")]

    def __str__(self):
        return f"{self.employee.name} @ {self.location.name}"
