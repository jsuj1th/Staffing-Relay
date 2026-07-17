"""Tests for SMS notification system with batching."""
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Employee
from apps.leaves.models import Leave
from apps.locations.models import Location
from apps.shifts.models import Shift
from .models import NotificationQueue, SmsLog
from .notifications import (
    queue_notification,
    send_notification_batch,
    send_all_pending_notifications,
    notify_shift_assigned,
    notify_leave_approved,
    notify_leave_rejected,
)
from .leave_menu import parse_date_input, build_confirmation_message


class NotificationQueueTests(TestCase):
    def setUp(self):
        """Set up test data."""
        self.location = Location.objects.create(
            name="Test Hospital",
            address="123 Main St",
            city="Testville",
            state="TX",
        )

        self.employee = Employee.objects.create(
            name="Test Employee",
            phone="+1555000001",
            employee_type=Employee.Type.PROVIDER,
            location=self.location,
        )

    def test_queue_notification_batched(self):
        """Notification queued for later batching."""
        notif = queue_notification(
            employee=self.employee,
            notification_type=NotificationQueue.NotificationType.SHIFT_ASSIGNED,
            message_body="Jul 25 | 09:00 - 17:00",
            send_immediately=False,
        )

        self.assertFalse(notif.is_sent)
        self.assertIsNone(notif.sent_at)
        self.assertGreater(notif.scheduled_send_at, timezone.now())

    def test_queue_notification_immediate(self):
        """Notification sent immediately if requested."""
        notif = queue_notification(
            employee=self.employee,
            notification_type=NotificationQueue.NotificationType.SHIFT_ASSIGNED,
            message_body="Jul 25 | 09:00 - 17:00",
            send_immediately=True,
        )

        # After sending, notification should be marked sent
        notif.refresh_from_db()
        self.assertTrue(notif.is_sent)
        self.assertIsNotNone(notif.sent_at)

    def test_batch_multiple_shifts(self):
        """Multiple shift notifications batched into one SMS."""
        # Queue 3 shift notifications
        today = timezone.localdate()
        for i in range(3):
            queue_notification(
                employee=self.employee,
                notification_type=NotificationQueue.NotificationType.SHIFT_ASSIGNED,
                message_body=f"{(today + timedelta(days=i)).strftime('%a, %b %d')} | 09:00 - 17:00",
                send_immediately=False,
                batch_window_minutes=0,  # Send immediately
            )

        # Send batch
        send_notification_batch(self.employee)

        # All should be marked sent
        pending = NotificationQueue.objects.filter(
            employee=self.employee,
            is_sent=False,
        )
        self.assertEqual(pending.count(), 0)

        # SMS log should have one entry with all shifts
        sms_log = SmsLog.objects.filter(
            employee=self.employee,
            inbound_msg="[Batch notification]",
        ).first()

        self.assertIsNotNone(sms_log)
        self.assertIn("SHIFTS ASSIGNED", sms_log.outbound_msg)
        self.assertIn("09:00 - 17:00", sms_log.outbound_msg)

    def test_notify_shift_assigned(self):
        """Convenience function for shift notifications."""
        today = timezone.localdate()
        shift = Shift.objects.create(
            employee=self.employee,
            date=today,
            start_time="09:00",
            end_time="17:00",
        )

        notif = notify_shift_assigned(shift, send_immediately=False)

        self.assertEqual(notif.employee, self.employee)
        self.assertEqual(
            notif.notification_type,
            NotificationQueue.NotificationType.SHIFT_ASSIGNED,
        )
        self.assertEqual(notif.related_object_id, shift.id)

    def test_notify_leave_approved(self):
        """Convenience function for leave approved notifications."""
        today = timezone.localdate()
        leave = Leave.objects.create(
            employee=self.employee,
            start_date=today,
            end_date=today,
            status=Leave.Status.APPROVED,
        )

        notif = notify_leave_approved(leave, send_immediately=False)

        self.assertEqual(notif.employee, self.employee)
        self.assertEqual(
            notif.notification_type,
            NotificationQueue.NotificationType.LEAVE_APPROVED,
        )
        self.assertIn("APPROVED", notif.message_body)

    def test_notify_leave_rejected(self):
        """Convenience function for leave rejected notifications."""
        today = timezone.localdate()
        leave = Leave.objects.create(
            employee=self.employee,
            start_date=today,
            end_date=today,
            status=Leave.Status.REJECTED,
        )

        notif = notify_leave_rejected(leave, send_immediately=False)

        self.assertEqual(notif.employee, self.employee)
        self.assertEqual(
            notif.notification_type,
            NotificationQueue.NotificationType.LEAVE_REJECTED,
        )

    def test_send_all_pending_notifications(self):
        """Cron job sends all due notifications."""
        # Queue 2 notifications for different employees
        employee2 = Employee.objects.create(
            name="Another Employee",
            phone="+1555000002",
            employee_type=Employee.Type.PROVIDER,
            location=self.location,
        )

        queue_notification(
            employee=self.employee,
            notification_type=NotificationQueue.NotificationType.SHIFT_ASSIGNED,
            message_body="Jul 25 | 09:00 - 17:00",
            send_immediately=False,
            batch_window_minutes=0,
        )

        queue_notification(
            employee=employee2,
            notification_type=NotificationQueue.NotificationType.SHIFT_ASSIGNED,
            message_body="Jul 26 | 09:00 - 17:00",
            send_immediately=False,
            batch_window_minutes=0,
        )

        # Run cron job
        count = send_all_pending_notifications()

        # Should process 2 employees
        self.assertEqual(count, 2)


class LeaveMenuTests(TestCase):
    def test_parse_single_date(self):
        """Parse single date input (MMDD)."""
        today = timezone.localdate()
        future_month = today.month if today.day < 15 else (today.month % 12) + 1
        future_day = 20

        start, end = parse_date_input(f"{future_month:02d}{future_day:02d}")

        self.assertIsNotNone(start)
        self.assertEqual(start, end)

    def test_parse_date_range(self):
        """Parse date range input (MMDD-MMDD)."""
        start, end = parse_date_input("0725-0730")

        self.assertIsNotNone(start)
        self.assertIsNotNone(end)
        self.assertEqual((end - start).days, 5)

    def test_parse_invalid_date(self):
        """Invalid date returns None."""
        start, end = parse_date_input("9999")

        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_build_confirmation_message(self):
        """Build formatted confirmation message."""
        today = timezone.localdate()

        msg = build_confirmation_message(
            leave_type="VACATION",
            start_date=today,
            end_date=today + timedelta(days=2),
            reason="Summer trip",
        )

        self.assertIn("Vacation", msg)  # Note: capitalized in message
        self.assertIn("3 days", msg)
        self.assertIn("Summer trip", msg)
        self.assertIn("YES", msg)
        self.assertIn("NO", msg)
