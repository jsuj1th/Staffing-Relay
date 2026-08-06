"""A shift records where it is worked, so shared staff land in the right column."""
import json
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import Employee
from apps.locations.models import EmployeeLocation, Location
from apps.messaging.models import NotificationSetting
from apps.shifts.models import Shift


class ShiftLocationTests(TestCase):
    def setUp(self):
        self.elgin = Location.objects.create(name="Elgin Pediatrics")
        self.river = Location.objects.create(name="River Ridge Pediatrics")
        # Shared employee: no home location, linked to River Ridge first.
        self.emily = Employee.objects.create(
            name="Emily", phone="+15550001111", employee_type=Employee.Type.MANAGEMENT,
        )
        EmployeeLocation.objects.create(employee=self.emily, location=self.river, is_primary=True)
        EmployeeLocation.objects.create(employee=self.emily, location=self.elgin)

        self.user = User.objects.create_user("mgr", password="x")
        self.client.force_login(self.user)
        s = NotificationSetting.load()
        s.shift_sms_enabled = False  # keep tests from texting
        s.save()
        # Next Monday — a fixed offset could land on Sunday, which the combined
        # grid doesn't render, making this suite fail depending on the weekday.
        today = date.today()
        self.day = today + timedelta(days=7 - today.weekday())

    def _assign(self, location):
        return self.client.post(
            "/dashboard/api/add-shift/",
            json.dumps({
                "employee_id": self.emily.pk, "date": self.day.isoformat(),
                "location_id": location.pk, "start_time": "09:00", "end_time": "15:00",
            }),
            content_type="application/json",
        )

    def test_assignment_records_the_location_it_was_made_at(self):
        self.assertEqual(self._assign(self.elgin).status_code, 200)
        self.assertEqual(Shift.objects.get(employee=self.emily).location, self.elgin)

    def test_site_prefers_the_shifts_own_location_over_first_linked(self):
        self._assign(self.elgin)
        self.assertEqual(Shift.objects.get(employee=self.emily).site, self.elgin)

    def test_site_falls_back_when_location_was_never_recorded(self):
        shift = Shift.objects.create(
            employee=self.emily, date=self.day, start_time="09:00", end_time="15:00",
        )
        self.assertEqual(shift.site, self.river)  # first linked, as before

    def test_combined_schedule_shows_shift_under_its_own_location(self):
        self._assign(self.elgin)
        rows = {
            r["location"].name: r
            for r in self.client.get("/dashboard/combined/", {"date": self.day.isoformat()}).context["rows"]
            if r["location"]
        }
        elgin_names = [s.employee.name for c in rows["Elgin Pediatrics"]["cells"] for s in c["shifts"]]
        river_names = [s.employee.name for c in rows["River Ridge Pediatrics"]["cells"] for s in c["shifts"]]
        self.assertIn("Emily", elgin_names)
        self.assertNotIn("Emily", river_names)
