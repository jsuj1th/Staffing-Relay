from datetime import date, time
from django.test import TestCase

from apps.accounts.models import Employee
from apps.locations.models import Location
from apps.shifts.models import Shift


class ShiftModelTests(TestCase):
    def setUp(self):
        self.location = Location.objects.create(
            name="Test Hospital", address="1 Main St", city="Testville", state="TX"
        )
        self.employee = Employee.objects.create(
            name="Dr. Test",
            phone="+15550001234",
            employee_type=Employee.Type.PROVIDER,
            location=self.location,
        )

    def test_create_shift(self):
        shift = Shift.objects.create(
            employee=self.employee,
            date=date(2026, 8, 3),
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
        self.assertEqual(shift.employee, self.employee)
        self.assertIn(self.employee.name, str(shift))

    def test_multiple_shifts_same_day_allowed(self):
        """No overlap validation — split shifts are allowed."""
        Shift.objects.create(
            employee=self.employee, date=date(2026, 8, 3),
            start_time=time(7, 0), end_time=time(11, 0),
        )
        Shift.objects.create(
            employee=self.employee, date=date(2026, 8, 3),
            start_time=time(12, 0), end_time=time(16, 0),
        )
        self.assertEqual(
            Shift.objects.filter(employee=self.employee, date=date(2026, 8, 3)).count(),
            2,
        )
