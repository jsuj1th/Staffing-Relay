from datetime import date, timedelta
from django.core import mail
from django.test import TestCase

from apps.accounts.models import Employee
from apps.leaves.models import Leave
from apps.messaging.models import NotificationSetting


class LeaveEmailTests(TestCase):
    def setUp(self):
        self.emp = Employee.objects.create(
            name="Ada", phone="+15550001111", employee_type=Employee.Type.PROVIDER,
        )
        s = NotificationSetting.load()
        s.leave_email_recipients = "office@clinic.com, boss@clinic.com\n"
        s.save()
        mail.outbox = []

    def _leave(self):
        today = date.today()
        return Leave.objects.create(
            employee=self.emp, start_date=today, end_date=today + timedelta(days=1),
        )

    def test_request_emails_all_admins(self):
        self._leave()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(sorted(mail.outbox[0].to), ["boss@clinic.com", "office@clinic.com"])
        self.assertIn("Leave requested", mail.outbox[0].subject)
        self.assertIn("Ada", mail.outbox[0].body)

    def test_decision_emails_once_per_status_change(self):
        leave = self._leave()
        mail.outbox = []

        leave.status = Leave.Status.APPROVED
        leave.save()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Leave approved", mail.outbox[0].subject)

        leave.internal_note = "no status change"
        leave.save()
        self.assertEqual(len(mail.outbox), 1)

        leave.status = Leave.Status.REJECTED
        leave.save()
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Leave rejected", mail.outbox[1].subject)

    def test_toggle_off_sends_nothing(self):
        s = NotificationSetting.load()
        s.leave_email_enabled = False
        s.save()
        self._leave()
        self.assertEqual(mail.outbox, [])

    def test_no_recipients_sends_nothing(self):
        s = NotificationSetting.load()
        s.leave_email_recipients = ""
        s.save()
        self._leave()
        self.assertEqual(mail.outbox, [])
