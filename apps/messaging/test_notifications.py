"""Tests for SMS notification system with batching and menu flow."""
from datetime import timedelta, date
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from django.core.cache import cache

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
from .leave_menu import parse_date_input, build_confirmation_message, LeaveMenuState
from .session import (
    get_user_session,
    set_user_session,
    clear_user_session,
    start_leave_menu,
    process_menu_response,
    is_in_menu_flow,
)
from .views import _process_command


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

        parsed, _ = parse_date_input(f"{future_month:02d}{future_day:02d}")

        self.assertIsNotNone(parsed)

    def test_parse_past_date_becomes_next_year(self):
        """Past dates automatically shift to next year."""
        # January 5 is likely in the past if we're past Jan 5
        today = timezone.localdate()
        if today.month > 1 or (today.month == 1 and today.day > 5):
            parsed, _ = parse_date_input("0105")
            self.assertEqual(parsed.year, today.year + 1)
            self.assertEqual(parsed.month, 1)
            self.assertEqual(parsed.day, 5)

    def test_parse_invalid_date(self):
        """Invalid date returns None."""
        parsed, _ = parse_date_input("9999")

        self.assertIsNone(parsed)

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


class MenuSessionTests(TestCase):
    def setUp(self):
        """Set up test data for menu flow."""
        from apps.shifts.models import Shift

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

        # Add backup employees with shifts on test date (July 25) so coverage is OK
        today = timezone.localdate()
        test_date = today.replace(month=7, day=25)
        if test_date < today:
            test_date = test_date.replace(year=test_date.year + 1)

        backup_employees = []
        for i in range(3):
            emp = Employee.objects.create(
                name=f"Backup Employee {i}",
                phone=f"+155500000{i+2}",
                employee_type=Employee.Type.PROVIDER,
                location=self.location,
            )
            backup_employees.append(emp)
            # Assign shift on test date
            Shift.objects.create(
                employee=emp,
                date=test_date,
                start_time="09:00",
                end_time="17:00",
            )

        self.phone = "+1555000001"
        self.test_date = test_date
        cache.clear()

    def tearDown(self):
        """Clean up cache."""
        cache.clear()

    def test_session_management(self):
        """Test storing and retrieving session state."""
        session_data = {
            "state": LeaveMenuState.AWAITING_TYPE,
            "leave_type": None,
        }

        set_user_session(self.phone, session_data)
        retrieved = get_user_session(self.phone)

        self.assertEqual(retrieved["state"], LeaveMenuState.AWAITING_TYPE)
        self.assertIsNone(retrieved["leave_type"])

    def test_clear_session(self):
        """Test clearing session."""
        session_data = {"state": LeaveMenuState.AWAITING_TYPE}
        set_user_session(self.phone, session_data)

        # Verify it's set
        self.assertTrue(is_in_menu_flow(self.phone))

        # Clear it
        clear_user_session(self.phone)

        # Verify it's gone
        self.assertFalse(is_in_menu_flow(self.phone))

    def test_process_leave_type_response(self):
        """Test processing leave type selection."""
        start_leave_menu(self.phone)

        # User selects type 2 (Vacation)
        reply, leave = process_menu_response(self.phone, "2", self.employee)

        # Should transition to awaiting start date
        session = get_user_session(self.phone)
        self.assertEqual(session["state"], LeaveMenuState.AWAITING_START_DATE)
        self.assertEqual(session["leave_type"], "VACATION")
        self.assertIsNone(reply)  # Menu sends prompt separately

    def test_process_date_response(self):
        """Test processing date entry."""
        start_leave_menu(self.phone)
        process_menu_response(self.phone, "2", self.employee)  # Select type

        # User enters start date
        reply, leave = process_menu_response(self.phone, "0725", self.employee)

        # Should transition to awaiting duration (single or range)
        session = get_user_session(self.phone)
        self.assertEqual(session["state"], LeaveMenuState.AWAITING_DURATION)
        self.assertIsNotNone(session["start_date"])
        self.assertIsNone(reply)  # Menu sends prompt separately

    def test_complete_leave_menu_flow(self):
        """Test complete leave request via menu."""
        start_leave_menu(self.phone)

        # Step 1: Select type
        process_menu_response(self.phone, "2", self.employee)

        # Step 2: Enter start date
        process_menu_response(self.phone, "0725", self.employee)

        # Step 3: Choose single day
        process_menu_response(self.phone, "S", self.employee)

        # Step 4: Enter reason
        reply, _ = process_menu_response(self.phone, "Summer vacation", self.employee)

        # Should now be in confirmation step
        self.assertIn("YES", reply)
        self.assertIn("NO", reply)
        self.assertIn("Vacation", reply)

    def test_cancel_at_any_step(self):
        """Test cancelling at different steps."""
        start_leave_menu(self.phone)
        process_menu_response(self.phone, "2", self.employee)

        # Cancel after type selection
        reply, _ = process_menu_response(self.phone, "CANCEL", self.employee)

        self.assertIn("cancelled", reply.lower())
        self.assertFalse(is_in_menu_flow(self.phone))


class MenuUnrecognizedTextTests(TestCase):
    def setUp(self):
        """Set up test data for unrecognized text tests."""
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

        self.phone = "+1555000001"
        cache.clear()

    def tearDown(self):
        """Clean up cache."""
        cache.clear()

    @patch("apps.messaging.leave_menu.send_sms")
    def test_unrecognized_text_starts_menu(self, mock_send_sms):
        """Verify various unrecognized inputs trigger menu."""
        # Use strings that won't match any parser keywords
        unrecognized_strings = ["HI", "hey", "xyz123", "random garbage"]

        for text in unrecognized_strings:
            # Clear session before each test
            cache.clear()
            mock_send_sms.reset_mock()

            # Process the unrecognized text
            reply, leave = _process_command(self.phone, text, self.employee)

            # Verify menu was started (reply is None, menu sends separately)
            self.assertIsNone(reply, f"Expected None reply for '{text}', got {reply}")
            self.assertIsNone(leave)

            # Verify session was created with AWAITING_TYPE state
            session = get_user_session(self.phone)
            self.assertIsNotNone(session, f"Session not created for '{text}'")
            self.assertEqual(
                session.get("state"),
                LeaveMenuState.AWAITING_TYPE,
                f"Expected AWAITING_TYPE state for '{text}', got {session.get('state')}",
            )

            # Verify menu prompt was sent
            mock_send_sms.assert_called_once()
            call_args = mock_send_sms.call_args
            sent_message = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("message", "")
            self.assertIn("RELAY LEAVE REQUEST", sent_message, f"Menu not sent for '{text}'")

    @patch("apps.messaging.leave_menu.send_sms")
    def test_menu_flow_from_unrecognized_hi(self, mock_send_sms):
        """Complete flow starting from unrecognized 'HI' through full menu sequence."""
        # Step 1: Send "HI" - unrecognized text triggers menu
        reply, leave = _process_command(self.phone, "HI", self.employee)
        self.assertIsNone(reply)
        self.assertIsNone(leave)

        # Verify menu step 1 was sent
        self.assertEqual(mock_send_sms.call_count, 1)
        first_call = mock_send_sms.call_args[0][1]
        self.assertIn("RELAY LEAVE REQUEST", first_call)
        self.assertIn("leave type", first_call.lower())
        mock_send_sms.reset_mock()

        # Step 2: Select Vacation (option 2)
        reply, leave = _process_command(self.phone, "2", self.employee)
        self.assertIsNone(reply)
        self.assertIsNone(leave)

        # Verify menu step 2 was sent (start date prompt)
        self.assertEqual(mock_send_sms.call_count, 1)
        second_call = mock_send_sms.call_args[0][1]
        self.assertIn("START DATE", second_call)
        mock_send_sms.reset_mock()

        # Step 3: Enter start date (0725 = July 25)
        reply, leave = _process_command(self.phone, "0725", self.employee)
        self.assertIsNone(reply)
        self.assertIsNone(leave)

        # Verify menu step 3 was sent (duration prompt)
        self.assertEqual(mock_send_sms.call_count, 1)
        third_call = mock_send_sms.call_args[0][1]
        self.assertIn("DURATION", third_call)
        self.assertIn("Single day", third_call)
        mock_send_sms.reset_mock()

        # Step 4: Choose single day
        reply, leave = _process_command(self.phone, "S", self.employee)
        self.assertIsNone(reply)
        self.assertIsNone(leave)

        # Verify menu step 5 was sent (reason prompt)
        self.assertEqual(mock_send_sms.call_count, 1)
        fourth_call = mock_send_sms.call_args[0][1]
        self.assertIn("REASON", fourth_call)
        mock_send_sms.reset_mock()

        # Step 5: Enter reason
        reply, leave = _process_command(self.phone, "Summer vacation", self.employee)

        # Should return confirmation message (reply is not None at confirmation step)
        self.assertIsNotNone(reply)
        self.assertIsNone(leave)  # Leave not created yet
        self.assertIn("YES", reply)
        self.assertIn("NO", reply)
        self.assertIn("Vacation", reply)
        self.assertIn("Summer vacation", reply)
        mock_send_sms.reset_mock()

        # Step 6: Confirm YES
        reply, leave = _process_command(self.phone, "YES", self.employee)

        # Should return success message and create leave
        self.assertIsNotNone(reply)
        self.assertIsNotNone(leave)
        self.assertEqual(leave.employee, self.employee)
        self.assertEqual(leave.reason, "Summer vacation")
        # Menu leaves should never be auto-approved (APPROVED status)
        # They can be PENDING (awaiting admin) or REJECTED (insufficient coverage)
        # But NOT APPROVED (that's dashboard-only)
        self.assertIn(leave.status, [Leave.Status.PENDING, Leave.Status.REJECTED])
        # Verify it's a vacation leave by checking internal_note contains VACATION
        self.assertIn("VACATION", leave.internal_note)
        # If approved by coverage, should mention admin review. If rejected, should mention rejection.
        self.assertTrue(
            "awaiting admin review" in reply.lower() or "cannot be approved" in reply.lower(),
            f"Unexpected reply message: {reply}"
        )

        # Verify session was cleared
        self.assertFalse(is_in_menu_flow(self.phone))
