from datetime import time
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Employee
from apps.dashboard.views import public_schedule_path
from apps.shifts.models import Shift


class PublicScheduleTests(TestCase):
    def setUp(self):
        self.emp = Employee.objects.create(
            name="Ada", phone="+15550001111", employee_type=Employee.Type.PROVIDER,
        )
        self.other = Employee.objects.create(
            name="Grace", phone="+15550002222", employee_type=Employee.Type.PROVIDER,
        )
        today = timezone.localdate()
        for emp in (self.emp, self.other):
            Shift.objects.create(
                employee=emp, date=today, start_time=time(9, 0), end_time=time(16, 0),
            )

    def test_all_staff_link_is_public_and_shows_everyone(self):
        r = self.client.get(public_schedule_path())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Ada")
        self.assertContains(r, "Grace")

    def test_personal_link_shows_only_that_employee(self):
        r = self.client.get(public_schedule_path(self.emp))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Ada")
        self.assertNotContains(r, "Grace")

    def test_tampered_token_404s(self):
        self.assertEqual(self.client.get("/schedule/bogus-token/").status_code, 404)

    def test_month_navigation(self):
        r = self.client.get(public_schedule_path(), {"month": "2026-01"})
        self.assertContains(r, "January 2026")
