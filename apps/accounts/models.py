import logging
import re
from django.db import models

logger = logging.getLogger(__name__)


class Employee(models.Model):
    class Type(models.TextChoices):
        PROVIDER = "PROVIDER", "Provider"
        MEDICAL_ASSISTANT = "MEDICAL_ASSISTANT", "Medical Assistant"
        FRONT_DESK = "FRONT_DESK", "Front Desk"
        MANAGEMENT = "MANAGEMENT", "Management"

    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, unique=True, help_text="E.164 format, e.g. +12223334444")
    employee_type = models.CharField(max_length=30, choices=Type.choices)
    # For PROVIDER and MEDICAL_ASSISTANT: location is required (enforced in forms/serializers)
    # For FRONT_DESK and MANAGEMENT: location is null; use EmployeeLocation M2M instead
    location = models.ForeignKey(
        "locations.Location",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="direct_employees",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    @staticmethod
    def normalize_phone(raw):
        """Coerce a phone to E.164 (+1XXXXXXXXXX). US-only. ponytail: no libphonenumber."""
        digits = re.sub(r"\D", "", raw or "")
        if len(digits) == 10:
            digits = "1" + digits
        return "+" + digits if digits else (raw or "")

    def save(self, *args, **kwargs):
        self.phone = self.normalize_phone(self.phone)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.get_employee_type_display()})"

    @property
    def is_location_specific(self):
        return self.employee_type in (self.Type.PROVIDER, self.Type.MEDICAL_ASSISTANT)

    @property
    def is_shared(self):
        return self.employee_type in (self.Type.FRONT_DESK, self.Type.MANAGEMENT)
