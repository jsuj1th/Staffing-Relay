from datetime import date, timedelta
from unittest.mock import patch

from django.core import mail
from django.test import TestCase

from apps.accounts.models import Employee
from apps.leaves.models import Leave
from apps.messaging.models import AdminContact, NotificationSetting


class LeaveAlertTests(TestCase):
    def setUp(self):
        self.emp = Employee.objects.create(
            name="Ada", phone="+15550001111", employee_type=Employee.Type.PROVIDER,
        )
        self.mailer = AdminContact.objects.create(
            name="Office", email="office@clinic.com", channel=AdminContact.Channel.EMAIL,
        )
        self.texter = AdminContact.objects.create(
            name="Owner", phone="+15550009999", channel=AdminContact.Channel.SMS,
        )
        self.both = AdminContact.objects.create(
            name="Manager", email="mgr@clinic.com", phone="+15550008888",
            channel=AdminContact.Channel.BOTH,
        )
        mail.outbox = []

    def _leave(self):
        today = date.today()
        return Leave.objects.create(
            employee=self.emp, start_date=today, end_date=today + timedelta(days=1),
        )

    def test_request_uses_each_contacts_chosen_channel(self):
        with patch("apps.messaging.leave_alerts.send_sms", return_value=True) as sms:
            self._leave()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(sorted(mail.outbox[0].to), ["mgr@clinic.com", "office@clinic.com"])
        self.assertEqual(sorted(c.args[0] for c in sms.call_args_list),
                         ["+15550008888", "+15550009999"])

    def test_decision_alerts_once_per_status_change(self):
        with patch("apps.messaging.leave_alerts.send_sms", return_value=True):
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

    def test_paused_and_inactive_contacts_are_skipped(self):
        AdminContact.objects.update(is_active=False)
        self.mailer.is_active = True
        self.mailer.save()
        with patch("apps.messaging.leave_alerts.send_sms", return_value=True) as sms:
            self._leave()
        self.assertEqual(mail.outbox[0].to, ["office@clinic.com"])
        sms.assert_not_called()

    def test_auto_rejected_leave_emails_admins_once(self):
        """SMS auto-reject inserts the leave already REJECTED (no PENDING step),
        so admins get exactly one email and it says rejected."""
        today = date.today()
        with patch("apps.messaging.leave_alerts.send_sms", return_value=True):
            Leave.objects.create(
                employee=self.emp, start_date=today, end_date=today,
                status=Leave.Status.REJECTED,
                internal_note="[MENU] SICK - Coverage: impossible",
            )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Leave rejected", mail.outbox[0].subject)
        self.assertIn("Rejected", mail.outbox[0].body)

    def test_master_toggle_off_sends_nothing(self):
        s = NotificationSetting.load()
        s.leave_alerts_enabled = False
        s.save()
        with patch("apps.messaging.leave_alerts.send_sms", return_value=True) as sms:
            self._leave()
        self.assertEqual(mail.outbox, [])
        sms.assert_not_called()

    def test_no_contacts_sends_nothing(self):
        AdminContact.objects.all().delete()
        self._leave()
        self.assertEqual(mail.outbox, [])
