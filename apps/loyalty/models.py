from django.db import models


class LoyaltyPoint(models.Model):
    """Stub model — logic will be implemented in a future phase."""
    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="loyalty_points",
    )
    points = models.IntegerField()
    reason = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.employee.name}: {self.points} pts ({self.reason})"
