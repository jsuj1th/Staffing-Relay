"""
Tests for SMS parser and webhook handler.
"""
import json
from datetime import date, timedelta
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from apps.accounts.models import Employee
from apps.locations.models import Location
from apps.leaves.models import Leave
from apps.messaging.models import SmsLog
from apps.messaging.parser import parse_sms


class SmsParserTests(TestCase):
    def test_leave_single_day(self):
        cmd = parse_sms("LEAVE 2025-08-01")
        self.assertEqual(cmd.command, "leave")
        self.assertEqual(cmd.start_date, date(2025, 8, 1))
        self.assertEqual(cmd.end_date, date(2025, 8, 1))
        self.assertEqual(cmd.reason, "")

    def test_leave_date_range(self):
        cmd = parse_sms("LEAVE 2025-08-01 2025-08-05")
        self.assertEqual(cmd.command, "leave")
        self.assertEqual(cmd.start_date, date(2025, 8, 1))
        self.assertEqual(cmd.end_date, date(2025, 8, 5))

    def test_leave_with_reason(self):
        cmd = parse_sms("LEAVE 2025-08-01 2025-08-03 Annual checkup")
        self.assertEqual(cmd.command, "leave")
        self.assertEqual(cmd.reason, "Annual checkup")

    def test_leave_case_insensitive(self):
        cmd = parse_sms("leave 2025-09-10")
        self.assertEqual(cmd.command, "leave")

    def test_leave_no_date(self):
        cmd = parse_sms("LEAVE next monday")
        self.assertEqual(cmd.command, "unknown")

    def test_status_command(self):
        cmd = parse_sms("STATUS")
        self.assertEqual(cmd.command, "status")

    def test_help_command(self):
        cmd = parse_sms("HELP")
        self.assertEqual(cmd.command, "help")

    def test_cancel_with_date(self):
        cmd = parse_sms("CANCEL 2025-08-01")
        self.assertEqual(cmd.command, "cancel")
        self.assertEqual(cmd.cancel_date, date(2025, 8, 1))

    def test_cancel_without_date(self):
        cmd = parse_sms("CANCEL")
        self.assertEqual(cmd.command, "cancel")
        self.assertIsNone(cmd.cancel_date)

    def test_unknown_command(self):
        cmd = parse_sms("Hi there!")
        self.assertEqual(cmd.command, "unknown")

    def test_off_keyword(self):
        cmd = parse_sms("OFF 2025-08-01")
        self.assertEqual(cmd.command, "leave")


# Pin to "dev mode" (no signature check) so these tests exercise message
# handling regardless of whether a real TELNYX_PUBLIC_KEY is set in .env.
@override_settings(TELNYX_PUBLIC_KEY="")
class WebhookTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.location = Location.objects.create(
            name="Test Hosp", address="1 St", city="Chicago", state="IL"
        )
        # 3 providers, 4 MAs
        for i in range(3):
            Employee.objects.create(
                name=f"Provider {i}", phone=f"+155500001{i}",
                employee_type=Employee.Type.PROVIDER, location=self.location,
            )
        for i in range(4):
            Employee.objects.create(
                name=f"MA {i}", phone=f"+155500002{i}",
                employee_type=Employee.Type.MEDICAL_ASSISTANT, location=self.location,
            )
        self.employee = Employee.objects.filter(employee_type=Employee.Type.PROVIDER).first()
        self.future_date = (date.today() + timedelta(days=10)).isoformat()
        self.webhook_url = "/webhooks/telnyx/"

    def _post_sms(self, from_phone, text):
        payload = {
            "data": {
                "event_type": "message.received",
                "payload": {
                    "from": {"phone_number": from_phone},
                    "text": text,
                },
            }
        }
        return self.client.post(
            self.webhook_url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_webhook_returns_200(self):
        resp = self._post_sms(self.employee.phone, "HELP")
        self.assertEqual(resp.status_code, 200)

    def test_unknown_number_response(self):
        resp = self._post_sms("+19999999999", "LEAVE 2025-08-01")
        self.assertEqual(resp.status_code, 200)
        log = SmsLog.objects.filter(from_phone="+19999999999").first()
        self.assertIsNotNone(log)
        self.assertIn("not registered", log.outbound_msg)

    def test_leave_request_creates_leave(self):
        resp = self._post_sms(self.employee.phone, f"LEAVE {self.future_date}")
        self.assertEqual(resp.status_code, 200)
        leave = Leave.objects.filter(employee=self.employee).first()
        self.assertIsNotNone(leave)
        self.assertIn(leave.status, [Leave.Status.APPROVED, Leave.Status.REJECTED, Leave.Status.EXTREME])

    def test_leave_request_logs_sms(self):
        self._post_sms(self.employee.phone, f"LEAVE {self.future_date}")
        log = SmsLog.objects.filter(employee=self.employee).first()
        self.assertIsNotNone(log)
        self.assertNotEqual(log.outbound_msg, "")

    def test_status_no_leaves(self):
        resp = self._post_sms(self.employee.phone, "STATUS")
        self.assertEqual(resp.status_code, 200)
        log = SmsLog.objects.filter(employee=self.employee).first()
        self.assertIn("no upcoming", log.outbound_msg.lower())

    def test_cancel_no_leaves(self):
        resp = self._post_sms(self.employee.phone, "CANCEL")
        self.assertEqual(resp.status_code, 200)
        log = SmsLog.objects.filter(employee=self.employee).first()
        self.assertIn("no upcoming", log.outbound_msg.lower())

    def test_past_date_rejected(self):
        past_date = (date.today() - timedelta(days=1)).isoformat()
        self._post_sms(self.employee.phone, f"LEAVE {past_date}")
        log = SmsLog.objects.filter(employee=self.employee).first()
        self.assertIn("past", log.outbound_msg.lower())

    def test_non_message_event_ignored(self):
        payload = {"data": {"event_type": "message.sent", "payload": {}}}
        resp = self.client.post(
            self.webhook_url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(SmsLog.objects.count(), 0)
