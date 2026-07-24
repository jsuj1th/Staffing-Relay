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
    notify_leave_cancelled,
)
from .leave_menu import parse_date_input, build_confirmation_message, LeaveMenuState
from .session import (
    get_user_session,
    set_user_session,
    clear_user_session,
    start_leave_menu,
    start_main_menu,
    process_menu_response,
    is_in_menu_flow,
)
from .views import _process_command


class NotificationQueueTests(TestCase):
    def setUp(self):
        """Set up test data."""
        _p = patch("apps.messaging.notifications.send_sms", return_value=True)
        self.addCleanup(_p.stop)
        _p.start()
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

    def test_process_date_response(self):
        """Test processing date entry."""
        start_leave_menu(self.phone)

        # User enters start date (type selection removed)
        reply, leave = process_menu_response(self.phone, "0725", self.employee)

        # Should transition to awaiting duration (single or range)
        session = get_user_session(self.phone)
        self.assertEqual(session["state"], LeaveMenuState.AWAITING_DURATION)
        self.assertIsNotNone(session["start_date"])
        self.assertIsNone(reply)  # Menu sends prompt separately

    def test_complete_leave_menu_flow(self):
        """Test complete leave request via menu."""
        start_leave_menu(self.phone)

        # Step 1: Enter start date (type selection removed)
        process_menu_response(self.phone, "0725", self.employee)

        # Step 2: Choose single day
        process_menu_response(self.phone, "S", self.employee)

        # Step 3: Enter reason
        reply, _ = process_menu_response(self.phone, "Summer vacation", self.employee)

        # Should now be in confirmation step
        self.assertIn("YES", reply)
        self.assertIn("NO", reply)
        self.assertIn("Jul", reply)  # Date confirmation

    def test_cancel_at_any_step(self):
        """Test cancelling at different steps."""
        start_leave_menu(self.phone)

        # Cancel after start date prompt
        reply, _ = process_menu_response(self.phone, "EXIT", self.employee)

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

            # Verify session was created with AWAITING_START_DATE state (type selection removed)
            session = get_user_session(self.phone)
            self.assertIsNotNone(session, f"Session not created for '{text}'")
            self.assertEqual(
                session.get("state"),
                LeaveMenuState.AWAITING_START_DATE,
                f"Expected AWAITING_START_DATE state for '{text}', got {session.get('state')}",
            )

            # Verify start date prompt was sent
            mock_send_sms.assert_called_once()
            call_args = mock_send_sms.call_args
            sent_message = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("message", "")
            self.assertIn("START DATE", sent_message, f"Start date prompt not sent for '{text}'")

    @patch("apps.messaging.leave_menu.send_sms")
    def test_menu_flow_from_unrecognized_hi(self, mock_send_sms):
        """Complete flow starting from unrecognized 'HI' through full menu sequence."""
        # Step 1: Send "HI" - unrecognized text triggers leave request (type selection removed)
        reply, leave = _process_command(self.phone, "HI", self.employee)
        self.assertIsNone(reply)
        self.assertIsNone(leave)

        # Verify start date prompt was sent (skipped type selection)
        self.assertEqual(mock_send_sms.call_count, 1)
        first_call = mock_send_sms.call_args[0][1]
        self.assertIn("START DATE", first_call)
        mock_send_sms.reset_mock()

        # Step 2: Enter start date (0725 = July 25)
        reply, leave = _process_command(self.phone, "0725", self.employee)
        self.assertIsNone(reply)
        self.assertIsNone(leave)

        # Verify duration prompt was sent
        self.assertEqual(mock_send_sms.call_count, 1)
        second_call = mock_send_sms.call_args[0][1]
        self.assertIn("DURATION", second_call)
        self.assertIn("Single day", second_call)
        mock_send_sms.reset_mock()

        # Step 3: Choose single day
        reply, leave = _process_command(self.phone, "S", self.employee)
        self.assertIsNone(reply)
        self.assertIsNone(leave)

        # Verify reason prompt was sent
        self.assertEqual(mock_send_sms.call_count, 1)
        third_call = mock_send_sms.call_args[0][1]
        self.assertIn("REASON", third_call)
        mock_send_sms.reset_mock()

        # Step 4: Enter reason
        reply, leave = _process_command(self.phone, "Summer vacation", self.employee)

        # Should return confirmation message (reply is not None at confirmation step)
        self.assertIsNotNone(reply)
        self.assertIsNone(leave)  # Leave not created yet
        self.assertIn("YES", reply)
        self.assertIn("NO", reply)
        self.assertIn("Jul 25", reply)  # Date confirmation
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
        # Verify it's a menu leave (type not tracked, defaults to LEAVE)
        self.assertIn("LEAVE", leave.internal_note)
        # If approved by coverage, should mention admin review. If rejected, should mention rejection.
        self.assertTrue(
            "awaiting admin review" in reply.lower() or "cannot be approved" in reply.lower(),
            f"Unexpected reply message: {reply}"
        )

        # Verify session was cleared
        self.assertFalse(is_in_menu_flow(self.phone))


class MainMenuTests(TestCase):
    def setUp(self):
        """Set up test data for main menu tests."""
        _p = patch("apps.messaging.notifications.send_sms", return_value=True)
        self.addCleanup(_p.stop)
        _p.start()
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
    def test_main_menu_triggered_by_menu_command(self, mock_send_sms):
        """MENU command triggers main menu prompt."""
        reply, leave = _process_command(self.phone, "MENU", self.employee)

        # Menu sends its own prompt, so reply should be None
        self.assertIsNone(reply)
        self.assertIsNone(leave)

        # Verify session was created
        session = get_user_session(self.phone)
        self.assertIsNotNone(session)
        self.assertEqual(session["state"], LeaveMenuState.AWAITING_MAIN_CHOICE)

        # Verify main menu was sent
        mock_send_sms.assert_called_once()
        sent_message = mock_send_sms.call_args[0][1]
        self.assertIn("RELAY MENU", sent_message)
        self.assertIn("1 = Request Leave", sent_message)
        self.assertIn("2 = Check Leave Status", sent_message)
        self.assertIn("3 = Cancel Leave", sent_message)
        self.assertIn("4 = Help", sent_message)

    @patch("apps.messaging.leave_menu.send_sms")
    def test_status_command_shows_leaves(self, mock_send_sms):
        """STATUS command displays leave status without session."""
        # Create some test leaves
        today = timezone.localdate()
        test_date = today.replace(month=7, day=25)
        if test_date < today:
            test_date = test_date.replace(year=test_date.year + 1)

        pending_leave = Leave.objects.create(
            employee=self.employee,
            start_date=test_date,
            end_date=test_date,
            status=Leave.Status.PENDING,
        )

        approved_leave = Leave.objects.create(
            employee=self.employee,
            start_date=test_date + timedelta(days=5),
            end_date=test_date + timedelta(days=7),
            status=Leave.Status.APPROVED,
        )

        rejected_leave = Leave.objects.create(
            employee=self.employee,
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=10),
            status=Leave.Status.REJECTED,
        )

        # Send STATUS command
        reply, leave = _process_command(self.phone, "STATUS", self.employee)

        # Should return status message (not None)
        self.assertIsNotNone(reply)
        self.assertIsNone(leave)
        self.assertIn("YOUR LEAVE STATUS", reply)
        self.assertIn("Upcoming", reply)
        self.assertIn("Pending", reply)
        self.assertIn("Approved", reply)
        self.assertIn("Rejections", reply)

        # Should not create a session
        session = get_user_session(self.phone)
        self.assertFalse(session)

    @patch("apps.messaging.leave_menu.send_sms")
    def test_status_from_main_menu(self, mock_send_sms):
        """Main menu option 2 shows leave status."""
        # Create test leave
        today = timezone.localdate()
        test_date = today.replace(month=7, day=25)
        if test_date < today:
            test_date = test_date.replace(year=test_date.year + 1)

        Leave.objects.create(
            employee=self.employee,
            start_date=test_date,
            end_date=test_date,
            status=Leave.Status.PENDING,
        )

        # Start main menu
        reply, leave = _process_command(self.phone, "MENU", self.employee)
        self.assertIsNone(reply)  # Menu sends prompt
        mock_send_sms.reset_mock()

        # Select option 2 (Check Leave Status)
        reply, leave = _process_command(self.phone, "2", self.employee)

        # Should return status message
        self.assertIsNotNone(reply)
        self.assertIsNone(leave)
        self.assertIn("YOUR LEAVE STATUS", reply)

        # Session should be cleared
        self.assertFalse(is_in_menu_flow(self.phone))

    @patch("apps.messaging.leave_menu.send_sms")
    def test_main_menu_option_1_starts_leave_request(self, mock_send_sms):
        """Main menu option 1 starts leave request flow."""
        # Start main menu
        reply, leave = _process_command(self.phone, "MENU", self.employee)
        self.assertIsNone(reply)
        mock_send_sms.reset_mock()

        # Select option 1 (Request Leave)
        reply, leave = _process_command(self.phone, "1", self.employee)

        # Should transition to leave request flow (no reply, menu sends prompt)
        self.assertIsNone(reply)
        self.assertIsNone(leave)

        # Verify state changed to AWAITING_START_DATE (type selection removed)
        session = get_user_session(self.phone)
        self.assertEqual(session["state"], LeaveMenuState.AWAITING_START_DATE)

        # Verify start date menu was sent
        mock_send_sms.assert_called_once()
        sent_message = mock_send_sms.call_args[0][1]
        self.assertIn("START DATE", sent_message)

    @patch("apps.messaging.leave_menu.send_sms")
    def test_main_menu_option_3_cancels_single_leave(self, mock_send_sms):
        """Main menu option 3 cancels leave when user has single pending leave."""
        # Create a pending leave
        today = timezone.localdate()
        test_date = today.replace(month=7, day=25)
        if test_date < today:
            test_date = test_date.replace(year=test_date.year + 1)

        leave_obj = Leave.objects.create(
            employee=self.employee,
            start_date=test_date,
            end_date=test_date,
            status=Leave.Status.PENDING,
        )

        # Start main menu
        reply, leave = _process_command(self.phone, "MENU", self.employee)
        self.assertIsNone(reply)
        mock_send_sms.reset_mock()

        # Select option 3 (Cancel Leave)
        reply, leave = _process_command(self.phone, "3", self.employee)

        # Should return success message
        self.assertIsNotNone(reply)
        self.assertIsNone(leave)
        self.assertIn("cancelled", reply.lower())

        # Verify leave was cancelled
        leave_obj.refresh_from_db()
        self.assertEqual(leave_obj.status, Leave.Status.CANCELLED)

        # Session should be cleared
        self.assertFalse(is_in_menu_flow(self.phone))

    @patch("apps.messaging.leave_menu.send_sms")
    def test_cancel_leave_via_sms_sends_notification(self, mock_send_sms):
        """User cancels leave via SMS menu, notification is sent."""
        # Create an approved leave
        today = timezone.localdate()
        test_date = today.replace(month=7, day=25)
        if test_date < today:
            test_date = test_date.replace(year=test_date.year + 1)

        leave_obj = Leave.objects.create(
            employee=self.employee,
            start_date=test_date,
            end_date=test_date + timedelta(days=5),
            status=Leave.Status.APPROVED,
        )

        # Start main menu
        reply, leave = _process_command(self.phone, "MENU", self.employee)
        self.assertIsNone(reply)
        mock_send_sms.reset_mock()

        # Select option 3 (Cancel Leave)
        reply, leave = _process_command(self.phone, "3", self.employee)

        # Should return success message
        self.assertIsNotNone(reply)
        self.assertIsNone(leave)
        self.assertIn("cancelled", reply.lower())

        # Verify leave was cancelled
        leave_obj.refresh_from_db()
        self.assertEqual(leave_obj.status, Leave.Status.CANCELLED)

        # Verify notification was queued
        notif = NotificationQueue.objects.filter(
            employee=self.employee,
            notification_type=NotificationQueue.NotificationType.LEAVE_CANCELLED,
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("CANCELLED", notif.message_body)
        self.assertIn("6 days", notif.message_body)
        # Should be marked as sent (send_immediately=True)
        self.assertTrue(notif.is_sent)

    @patch("apps.messaging.leave_menu.send_sms")
    def test_main_menu_option_4_shows_help(self, mock_send_sms):
        """Main menu option 4 shows help."""
        # Start main menu
        reply, leave = _process_command(self.phone, "MENU", self.employee)
        self.assertIsNone(reply)
        mock_send_sms.reset_mock()

        # Select option 4 (Help)
        reply, leave = _process_command(self.phone, "4", self.employee)

        # Should return help message
        self.assertIsNotNone(reply)
        self.assertIsNone(leave)
        self.assertIn("HELP", reply)
        self.assertIn("MENU", reply)
        self.assertIn("STATUS", reply)

        # Session should be cleared
        self.assertFalse(is_in_menu_flow(self.phone))

    @patch("apps.messaging.leave_menu.send_sms")
    def test_main_menu_invalid_option_shows_error(self, mock_send_sms):
        """Invalid main menu option shows error and resends menu."""
        # Start main menu
        reply, leave = _process_command(self.phone, "MENU", self.employee)
        self.assertIsNone(reply)
        mock_send_sms.reset_mock()

        # Select invalid option
        reply, leave = _process_command(self.phone, "5", self.employee)

        # Should return error message
        self.assertIsNotNone(reply)
        self.assertIsNone(leave)
        self.assertIn("Invalid option", reply)

        # Menu should be resent
        mock_send_sms.assert_called_once()
        sent_message = mock_send_sms.call_args[0][1]
        self.assertIn("RELAY MENU", sent_message)

    @patch("apps.messaging.leave_menu.send_sms")
    def test_leave_command_still_works(self, mock_send_sms):
        """LEAVE command still works (skips type, goes to start date)."""
        reply, leave = _process_command(self.phone, "LEAVE", self.employee)

        # Menu sends its own prompt
        self.assertIsNone(reply)
        self.assertIsNone(leave)

        # Verify state is AWAITING_START_DATE (type selection removed)
        session = get_user_session(self.phone)
        self.assertEqual(session["state"], LeaveMenuState.AWAITING_START_DATE)

        # Verify start date prompt was sent
        mock_send_sms.assert_called_once()
        sent_message = mock_send_sms.call_args[0][1]
        self.assertIn("START DATE", sent_message)


class AdminLeaveManagementTests(TestCase):
    """Tests for admin leave approval/rejection/editing dashboard."""

    def setUp(self):
        """Set up test data for admin leave management."""
        from django.contrib.auth import get_user_model

        _p = patch("apps.messaging.notifications.send_sms", return_value=True)
        self.addCleanup(_p.stop)
        _p.start()

        User = get_user_model()

        self.location = Location.objects.create(
            name="Test Hospital",
            address="123 Main St",
            city="Testville",
            state="TX",
        )

        self.employee = Employee.objects.create(
            name="Test Employee",
            phone="+15550000001",
            employee_type=Employee.Type.PROVIDER,
            location=self.location,
        )

        self.admin_user = User.objects.create_user(
            username="admin",
            password="adminpass123",
        )

        today = timezone.localdate()
        self.test_date = today.replace(month=7, day=25)
        if self.test_date < today:
            self.test_date = self.test_date.replace(year=self.test_date.year + 1)

    def test_leave_list_view_shows_all_leaves(self):
        """GET /dashboard/leaves/ returns all leaves."""
        from django.test import Client

        # Create test leaves
        Leave.objects.create(
            employee=self.employee,
            start_date=self.test_date,
            end_date=self.test_date,
            status=Leave.Status.PENDING,
        )

        Leave.objects.create(
            employee=self.employee,
            start_date=self.test_date + timedelta(days=5),
            end_date=self.test_date + timedelta(days=7),
            status=Leave.Status.APPROVED,
        )

        client = Client()
        client.force_login(self.admin_user)
        response = client.get("/dashboard/leaves/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.employee.name)
        self.assertEqual(response.context["leaves"].count(), 2)

    def test_leave_list_shows_status_badges(self):
        """Status displayed correctly with badges."""
        from django.test import Client

        pending = Leave.objects.create(
            employee=self.employee,
            start_date=self.test_date,
            end_date=self.test_date,
            status=Leave.Status.PENDING,
        )

        approved = Leave.objects.create(
            employee=self.employee,
            start_date=self.test_date + timedelta(days=5),
            end_date=self.test_date + timedelta(days=5),
            status=Leave.Status.APPROVED,
        )

        client = Client()
        client.force_login(self.admin_user)
        response = client.get("/dashboard/leaves/")

        self.assertContains(response, "PENDING")
        self.assertContains(response, "APPROVED")

    def test_approve_leave_sends_notification(self):
        """Approve button works, SMS sent."""
        from django.test import Client

        leave = Leave.objects.create(
            employee=self.employee,
            start_date=self.test_date,
            end_date=self.test_date,
            status=Leave.Status.PENDING,
        )

        client = Client()
        client.force_login(self.admin_user)
        response = client.post(
            f"/dashboard/leaves/{leave.pk}/approve/",
            follow=True,
        )

        # Check redirect to list
        self.assertEqual(response.status_code, 200)

        # Verify leave was approved
        leave.refresh_from_db()
        self.assertEqual(leave.status, Leave.Status.APPROVED)
        self.assertEqual(leave.approved_by, self.admin_user)

        # Verify notification was queued
        notif = NotificationQueue.objects.filter(
            employee=self.employee,
            notification_type=NotificationQueue.NotificationType.LEAVE_APPROVED,
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("APPROVED", notif.message_body)

    def test_reject_leave_sends_notification(self):
        """Reject button works, SMS sent."""
        from django.test import Client

        leave = Leave.objects.create(
            employee=self.employee,
            start_date=self.test_date,
            end_date=self.test_date,
            status=Leave.Status.PENDING,
        )

        client = Client()
        client.force_login(self.admin_user)
        response = client.post(
            f"/dashboard/leaves/{leave.pk}/reject/",
            data={"reason": "Insufficient coverage"},
            follow=True,
        )

        # Check redirect to list
        self.assertEqual(response.status_code, 200)

        # Verify leave was rejected
        leave.refresh_from_db()
        self.assertEqual(leave.status, Leave.Status.REJECTED)
        self.assertEqual(leave.approved_by, self.admin_user)
        self.assertIn("Insufficient coverage", leave.internal_note)

        # Verify notification was queued
        notif = NotificationQueue.objects.filter(
            employee=self.employee,
            notification_type=NotificationQueue.NotificationType.LEAVE_REJECTED,
        ).first()
        self.assertIsNotNone(notif)

    def test_edit_leave_form_displays(self):
        """GET edit shows form."""
        from django.test import Client

        leave = Leave.objects.create(
            employee=self.employee,
            start_date=self.test_date,
            end_date=self.test_date,
            status=Leave.Status.PENDING,
        )

        client = Client()
        client.force_login(self.admin_user)
        response = client.get(f"/dashboard/leaves/{leave.pk}/edit/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("form", response.context)
        self.assertEqual(response.context["action"], "Edit")
        self.assertEqual(response.context["leave"], leave)

    def test_edit_leave_saves_changes(self):
        """POST edit saves changes."""
        from django.test import Client

        leave = Leave.objects.create(
            employee=self.employee,
            start_date=self.test_date,
            end_date=self.test_date,
            reason="Original reason",
            status=Leave.Status.PENDING,
        )

        new_employee = Employee.objects.create(
            name="Another Employee",
            phone="+15550000002",
            employee_type=Employee.Type.PROVIDER,
            location=self.location,
        )

        new_end_date = self.test_date + timedelta(days=2)

        client = Client()
        client.force_login(self.admin_user)
        response = client.post(
            f"/dashboard/leaves/{leave.pk}/edit/",
            data={
                "employee": new_employee.pk,
                "start_date": str(self.test_date),
                "end_date": str(new_end_date),
                "reason": "Updated reason",
                "status": Leave.Status.APPROVED,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        # Verify changes were saved
        leave.refresh_from_db()
        self.assertEqual(leave.employee, new_employee)
        self.assertEqual(leave.end_date, new_end_date)
        self.assertEqual(leave.reason, "Updated reason")
        self.assertEqual(leave.status, Leave.Status.APPROVED)
        self.assertEqual(leave.approved_by, self.admin_user)

    def test_edit_leave_already_approved(self):
        """Can edit approved leaves."""
        from django.test import Client

        leave = Leave.objects.create(
            employee=self.employee,
            start_date=self.test_date,
            end_date=self.test_date,
            status=Leave.Status.APPROVED,
            approved_by=self.admin_user,
        )

        client = Client()
        client.force_login(self.admin_user)

        # Should be able to access edit form
        response = client.get(f"/dashboard/leaves/{leave.pk}/edit/")
        self.assertEqual(response.status_code, 200)

        # Should be able to change status
        response = client.post(
            f"/dashboard/leaves/{leave.pk}/edit/",
            data={
                "employee": self.employee.pk,
                "start_date": str(self.test_date),
                "end_date": str(self.test_date),
                "reason": leave.reason,
                "status": Leave.Status.REJECTED,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        leave.refresh_from_db()
        self.assertEqual(leave.status, Leave.Status.REJECTED)

    def test_leave_approved_sends_notification(self):
        """Approve button sends notification with correct message format."""
        from django.test import Client

        leave = Leave.objects.create(
            employee=self.employee,
            start_date=self.test_date,
            end_date=self.test_date + timedelta(days=5),
            status=Leave.Status.PENDING,
        )

        client = Client()
        client.force_login(self.admin_user)
        response = client.post(
            f"/dashboard/leaves/{leave.pk}/approve/",
            follow=True,
        )

        # Check redirect to list
        self.assertEqual(response.status_code, 200)

        # Verify leave was approved
        leave.refresh_from_db()
        self.assertEqual(leave.status, Leave.Status.APPROVED)

        # Verify notification was queued with correct format
        notif = NotificationQueue.objects.filter(
            employee=self.employee,
            notification_type=NotificationQueue.NotificationType.LEAVE_APPROVED,
        ).first()
        self.assertIsNotNone(notif)
        # Message should include date range and day count
        self.assertIn("APPROVED", notif.message_body)
        self.assertIn("6 days", notif.message_body)  # Jul 25-30 is 6 days
        # Should be marked as sent (send_immediately=True)
        self.assertTrue(notif.is_sent)

    def test_cancel_leave_via_dashboard_sends_notification(self):
        """Cancel button via dashboard sends notification."""
        from django.test import Client

        leave = Leave.objects.create(
            employee=self.employee,
            start_date=self.test_date,
            end_date=self.test_date + timedelta(days=5),
            status=Leave.Status.APPROVED,
        )

        client = Client()
        client.force_login(self.admin_user)
        response = client.post(
            f"/dashboard/leaves/{leave.pk}/cancel/",
            follow=True,
        )

        # Check redirect to list
        self.assertEqual(response.status_code, 200)

        # Verify leave was cancelled
        leave.refresh_from_db()
        self.assertEqual(leave.status, Leave.Status.CANCELLED)
        self.assertEqual(leave.approved_by, self.admin_user)

        # Verify notification was queued
        notif = NotificationQueue.objects.filter(
            employee=self.employee,
            notification_type=NotificationQueue.NotificationType.LEAVE_CANCELLED,
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("CANCELLED", notif.message_body)
        self.assertIn("6 days", notif.message_body)
        # Should be marked as sent (send_immediately=True)
        self.assertTrue(notif.is_sent)


class GlobalCommandsMidFlowTests(TestCase):
    """MENU and STATUS must work even while a leave request is in progress."""

    def setUp(self):
        cache.clear()
        _p = patch("apps.messaging.leave_menu.send_sms", return_value=True)
        self.addCleanup(_p.stop)
        _p.start()
        loc = Location.objects.create(name="L", address="a", city="c", state="TX")
        self.employee = Employee.objects.create(
            name="Mid Flow", phone="+15550007777",
            employee_type=Employee.Type.PROVIDER, location=loc,
        )
        self.phone = "+15550007777"

    def test_menu_midflow_returns_to_main_menu(self):
        start_leave_menu(self.phone)  # now AWAITING_START_DATE
        result = process_menu_response(self.phone, "MENU", self.employee)
        self.assertEqual(result, (None, None))
        self.assertEqual(get_user_session(self.phone)["state"], LeaveMenuState.AWAITING_MAIN_CHOICE)

    def test_status_midflow_returns_status_and_clears(self):
        start_leave_menu(self.phone)
        reply, _ = process_menu_response(self.phone, "STATUS", self.employee)
        self.assertIn("LEAVE STATUS", reply)
        self.assertFalse(is_in_menu_flow(self.phone))
