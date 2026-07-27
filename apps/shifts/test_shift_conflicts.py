"""Double-bookings are flagged for attention, never blocked."""
import json
from datetime import date, time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import Employee
from apps.locations.models import EmployeeLocation, Location
from apps.messaging.models import NotificationSetting
from apps.shifts.models import Shift


class ShiftConflictTests(TestCase):
    def setUp(self):
        self.elgin = Location.objects.create(name="Elgin Pediatrics")
        self.river = Location.objects.create(name="River Ridge Pediatrics")
        self.doc = Employee.objects.create(
            name="Dr. Barrera", phone="+15550001111", employee_type=Employee.Type.PROVIDER,
            location=self.elgin,
        )
        EmployeeLocation.objects.create(employee=self.doc, location=self.river)
        self.user = User.objects.create_user("mgr", password="x")
        self.client.force_login(self.user)
        s = NotificationSetting.load()
        s.shift_sms_enabled = False
        s.save()
        self.day = date.today() + timedelta(days=5)

    def _shift(self, start, end, location=None):
        return Shift.objects.create(
            employee=self.doc, date=self.day, location=location or self.elgin,
            start_time=start, end_time=end,
        )

    def test_overlap_flags_both_shifts_without_blocking(self):
        first = self._shift(time(9, 0), time(17, 0))
        second = self._shift(time(13, 0), time(18, 0), location=self.river)

        self.assertEqual(Shift.objects.count(), 2)  # not blocked
        first.refresh_from_db()
        self.assertTrue(first.needs_attention)
        self.assertTrue(second.needs_attention)

    def test_back_to_back_shifts_are_not_a_conflict(self):
        first = self._shift(time(9, 0), time(12, 0))
        second = self._shift(time(12, 0), time(17, 0), location=self.river)

        first.refresh_from_db()
        self.assertFalse(first.needs_attention)
        self.assertFalse(second.needs_attention)

    def test_different_days_are_not_a_conflict(self):
        first = self._shift(time(9, 0), time(17, 0))
        Shift.objects.create(
            employee=self.doc, date=self.day + timedelta(days=1), location=self.river,
            start_time=time(9, 0), end_time=time(17, 0),
        )
        first.refresh_from_db()
        self.assertFalse(first.needs_attention)

    def test_editing_times_into_a_clash_flags_it(self):
        first = self._shift(time(9, 0), time(12, 0))
        later = self._shift(time(13, 0), time(17, 0), location=self.river)

        later.start_time = time(11, 0)  # now overlaps the morning shift
        later.save()

        first.refresh_from_db()
        self.assertTrue(first.needs_attention)
        self.assertTrue(later.needs_attention)

    def test_flag_can_still_be_cleared_on_a_clashing_shift(self):
        self._shift(time(9, 0), time(17, 0))
        second = self._shift(time(13, 0), time(18, 0), location=self.river)

        second.needs_attention = False
        second.save(update_fields=["needs_attention"])
        second.refresh_from_db()
        self.assertFalse(second.needs_attention)

    def test_api_returns_a_warning_naming_the_clash(self):
        self._shift(time(9, 0), time(17, 0))
        r = self.client.post(
            "/dashboard/api/add-shift/",
            json.dumps({
                "employee_id": self.doc.pk, "date": self.day.isoformat(),
                "location_id": self.river.pk, "start_time": "13:00", "end_time": "18:00",
            }),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        warning = r.json()["warning"]
        self.assertIn("already scheduled", warning)
        self.assertIn("Elgin Pediatrics", warning)

    def test_no_warning_when_there_is_no_clash(self):
        r = self.client.post(
            "/dashboard/api/add-shift/",
            json.dumps({
                "employee_id": self.doc.pk, "date": self.day.isoformat(),
                "location_id": self.elgin.pk, "start_time": "09:00", "end_time": "17:00",
            }),
            content_type="application/json",
        )
        self.assertIsNone(r.json()["warning"])
