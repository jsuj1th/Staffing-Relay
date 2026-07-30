from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Employee
from apps.locations.models import Location


class ProviderMultiLocationTests(TestCase):
    """Providers/MAs keep a home location (ratio anchor) but may also be linked
    to extra sites, so they show up as assignable there."""

    def setUp(self):
        User.objects.create_user("admin", password="x")
        self.client.login(username="admin", password="x")
        self.a = Location.objects.create(name="A", address="1", city="Austin", state="TX")
        self.b = Location.objects.create(name="B", address="2", city="Elgin", state="TX")

    def test_create_provider_with_extra_location(self):
        self.client.post(reverse("dashboard:employee_create"), {
            "name": "Dr Multi",
            "phone": "+15125550001",
            "employee_type": "PROVIDER",
            "location_id": self.a.id,
            "shared_location_ids": [str(self.a.id), str(self.b.id)],
        })
        emp = Employee.objects.get(phone="+15125550001")
        assert emp.location_id == self.a.id
        # home location is not duplicated into the link table
        assert list(emp.employee_locations.values_list("location_id", flat=True)) == [self.b.id]
        assert emp.location_display == "A, B"

    def test_edit_replaces_extra_locations(self):
        emp = Employee.objects.create(
            name="Dr Multi", phone="+15125550002",
            employee_type="MEDICAL_ASSISTANT", location=self.a,
        )
        emp.employee_locations.create(location=self.b)
        self.client.post(reverse("dashboard:employee_edit", args=[emp.pk]), {
            "name": emp.name, "phone": emp.phone,
            "employee_type": "MEDICAL_ASSISTANT",
            "location_id": self.b.id,
            "shared_location_ids": [str(self.a.id)],
            "is_active": "on",
        })
        emp.refresh_from_db()
        assert emp.location_id == self.b.id
        assert list(emp.employee_locations.values_list("location_id", flat=True)) == [self.a.id]
