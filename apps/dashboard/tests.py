"""
Tests for the dashboard app, particularly leave filtering by period.
"""
from datetime import date, timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from apps.accounts.models import Employee
from apps.locations.models import Location
from apps.leaves.models import Leave


class LeaveListViewTests(TestCase):
    def setUp(self):
        """Set up test data with leaves at various dates."""
        self.client = Client()

        # Create a test user (manager)
        self.user = User.objects.create_user(username='admin', password='admin123')

        # Create test location and employees
        self.location = Location.objects.create(
            name="Test Hospital",
            address="123 Main St",
            city="Testville",
            state="TX"
        )

        self.provider = Employee.objects.create(
            name="Test Provider",
            phone="+1555000001",
            employee_type=Employee.Type.PROVIDER,
            location=self.location,
        )

        self.ma = Employee.objects.create(
            name="Test MA",
            phone="+1555000002",
            employee_type=Employee.Type.MEDICAL_ASSISTANT,
            location=self.location,
        )

        # Set up reference dates
        self.today = timezone.localdate()
        self.week_ago = self.today - timedelta(days=7)
        self.two_weeks_ago = self.today - timedelta(days=14)
        self.month_ago = self.today - timedelta(days=30)
        self.two_months_ago = self.today - timedelta(days=60)

        # Create leaves at different time periods
        # 1. Leave taken last week (overlaps with both week and month filters)
        self.leave_week = Leave.objects.create(
            employee=self.provider,
            start_date=self.week_ago,
            end_date=self.week_ago,
            status=Leave.Status.APPROVED,
        )

        # 2. Leave taken 2 weeks ago (overlaps with month filter, not week)
        self.leave_month = Leave.objects.create(
            employee=self.ma,
            start_date=self.two_weeks_ago,
            end_date=self.two_weeks_ago,
            status=Leave.Status.PENDING,
        )

        # 3. Leave taken 2 months ago (does not overlap with week or month filters)
        self.leave_old = Leave.objects.create(
            employee=self.provider,
            start_date=self.two_months_ago,
            end_date=self.two_months_ago,
            status=Leave.Status.REJECTED,
        )

        # 4. Leave taken today (overlaps with both filters)
        self.leave_today = Leave.objects.create(
            employee=self.ma,
            start_date=self.today,
            end_date=self.today,
            status=Leave.Status.APPROVED,
        )

        # 5. Multi-day leave that spans into the week range
        self.leave_multiday = Leave.objects.create(
            employee=self.provider,
            start_date=self.two_weeks_ago,
            end_date=self.week_ago + timedelta(days=2),
            status=Leave.Status.APPROVED,
        )

    def test_leave_list_no_filter_shows_all(self):
        """Without a period filter, all leaves are shown."""
        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/leaves/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('leaves', response.context)
        leaves = response.context['leaves']

        # Should see all 5 leaves
        self.assertEqual(len(leaves), 5)

    def test_leave_list_period_week_filter(self):
        """Period filter 'week' shows only leaves taken in last 7 days."""
        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/leaves/?period=week')

        self.assertEqual(response.status_code, 200)
        leaves = list(response.context['leaves'])

        # Should show: leave_week (exactly 7 days ago), leave_today, leave_multiday
        # (multiday overlaps: end_date = week_ago + 2 days, start_date = 2 weeks ago)
        self.assertIn(self.leave_week, leaves, "leave_week should be in week filter")
        self.assertIn(self.leave_today, leaves, "leave_today should be in week filter")
        self.assertIn(self.leave_multiday, leaves, "leave_multiday should be in week filter (overlaps)")

        # Should NOT show: leave_month (2 weeks ago), leave_old (2 months ago)
        self.assertNotIn(self.leave_month, leaves, "leave_month should not be in week filter")
        self.assertNotIn(self.leave_old, leaves, "leave_old should not be in week filter")

    def test_leave_list_period_month_filter(self):
        """Period filter 'month' shows only leaves taken in last 30 days."""
        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/leaves/?period=month')

        self.assertEqual(response.status_code, 200)
        leaves = list(response.context['leaves'])

        # Should show: leave_week, leave_month, leave_today, leave_multiday
        self.assertIn(self.leave_week, leaves, "leave_week should be in month filter")
        self.assertIn(self.leave_month, leaves, "leave_month should be in month filter")
        self.assertIn(self.leave_today, leaves, "leave_today should be in month filter")
        self.assertIn(self.leave_multiday, leaves, "leave_multiday should be in month filter")

        # Should NOT show: leave_old (2 months ago)
        self.assertNotIn(self.leave_old, leaves, "leave_old should not be in month filter")

    def test_leave_list_period_invalid_ignored(self):
        """Invalid period parameter is ignored (shows all leaves)."""
        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/leaves/?period=invalid')

        self.assertEqual(response.status_code, 200)
        leaves = response.context['leaves']

        # Should show all leaves (invalid period is treated as no filter)
        self.assertEqual(len(leaves), 5)

    def test_leave_list_period_combined_with_status_filter(self):
        """Period filter can be combined with status filter."""
        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/leaves/?period=week&status=APPROVED')

        self.assertEqual(response.status_code, 200)
        leaves = list(response.context['leaves'])

        # Should show only APPROVED leaves from last week
        self.assertIn(self.leave_week, leaves, "APPROVED leave_week should be shown")
        self.assertIn(self.leave_today, leaves, "APPROVED leave_today should be shown")
        self.assertIn(self.leave_multiday, leaves, "APPROVED leave_multiday should be shown")

        # Should NOT show PENDING or REJECTED leaves
        self.assertNotIn(self.leave_month, leaves, "PENDING leave_month should not be shown")
        self.assertNotIn(self.leave_old, leaves, "REJECTED leave_old should not be shown")

    def test_leave_list_period_combined_with_location_filter(self):
        """Period filter can be combined with location filter."""
        # Create another location with a leave
        location2 = Location.objects.create(
            name="Other Hospital",
            address="456 Oak St",
            city="Otherville",
            state="CA"
        )
        other_provider = Employee.objects.create(
            name="Other Provider",
            phone="+1555000099",
            employee_type=Employee.Type.PROVIDER,
            location=location2,
        )
        other_leave = Leave.objects.create(
            employee=other_provider,
            start_date=self.week_ago,
            end_date=self.week_ago,
            status=Leave.Status.APPROVED,
        )

        self.client.login(username='admin', password='admin123')
        response = self.client.get(f'/dashboard/leaves/?period=week&location={self.location.id}')

        self.assertEqual(response.status_code, 200)
        leaves = list(response.context['leaves'])

        # Should show only leaves from test_location
        self.assertIn(self.leave_week, leaves)
        self.assertNotIn(other_leave, leaves, "Leave from different location should not be shown")

    def test_leave_list_multiday_leave_overlap_logic(self):
        """Multi-day leaves that span across period boundaries are correctly included."""
        # Create a leave that starts outside the window but ends inside
        early_start = self.today - timedelta(days=8)
        mid_end = self.today - timedelta(days=5)
        leave_overlaps = Leave.objects.create(
            employee=self.provider,
            start_date=early_start,
            end_date=mid_end,
            status=Leave.Status.APPROVED,
        )

        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/leaves/?period=week')

        leaves = list(response.context['leaves'])

        # Should be included because it overlaps with the week range
        # (end_date >= 7 days ago AND start_date <= today)
        self.assertIn(leave_overlaps, leaves, "Multiday leave spanning boundaries should be included")

    def test_leave_list_template_context_period_filter(self):
        """Context includes period_filter for template rendering."""
        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/leaves/?period=week')

        self.assertEqual(response.context['period_filter'], 'week')

    def test_leave_list_template_context_period_filter_empty(self):
        """Context includes period_filter even when no period is specified."""
        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/leaves/')

        self.assertEqual(response.context['period_filter'], '')


class LeaveListAuthenticationTests(TestCase):
    def test_leave_list_requires_login(self):
        """Leave list view requires authentication."""
        response = self.client.get('/dashboard/leaves/')

        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard/login/', response.url)


class EmployeeDetailTests(TestCase):
    def setUp(self):
        """Set up test data for employee detail view."""
        self.client = Client()
        self.user = User.objects.create_user(username='admin', password='admin123')

        self.location = Location.objects.create(
            name="Test Hospital",
            address="123 Main St",
            city="Testville",
            state="TX"
        )

        self.employee = Employee.objects.create(
            name="Test Employee",
            phone="+1555000001",
            employee_type=Employee.Type.PROVIDER,
            location=self.location,
        )

        self.today = timezone.localdate()
        self.week_ago = self.today - timedelta(days=7)

    def test_employee_detail_page_loads(self):
        """Employee detail page loads successfully."""
        self.client.login(username='admin', password='admin123')
        response = self.client.get(f'/dashboard/employees/{self.employee.pk}/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('employee', response.context)
        self.assertEqual(response.context['employee'], self.employee)

    def test_employee_detail_shows_leave_stats(self):
        """Employee detail page shows correct leave statistics."""
        # Create some leaves
        Leave.objects.create(
            employee=self.employee,
            start_date=self.week_ago,
            end_date=self.week_ago,
            status=Leave.Status.APPROVED,
        )
        Leave.objects.create(
            employee=self.employee,
            start_date=self.today,
            end_date=self.today,
            status=Leave.Status.REJECTED,
        )

        self.client.login(username='admin', password='admin123')
        response = self.client.get(f'/dashboard/employees/{self.employee.pk}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['leaves_week'], 1)
        self.assertEqual(response.context['leaves_total'], 1)  # Only approved

    def test_employee_detail_shows_leave_breakdown(self):
        """Employee detail shows breakdown by status."""
        Leave.objects.create(
            employee=self.employee,
            start_date=self.today,
            end_date=self.today,
            status=Leave.Status.APPROVED,
        )
        Leave.objects.create(
            employee=self.employee,
            start_date=self.today - timedelta(days=1),
            end_date=self.today - timedelta(days=1),
            status=Leave.Status.APPROVED,
        )
        Leave.objects.create(
            employee=self.employee,
            start_date=self.today - timedelta(days=2),
            end_date=self.today - timedelta(days=2),
            status=Leave.Status.REJECTED,
        )
        Leave.objects.create(
            employee=self.employee,
            start_date=self.today - timedelta(days=3),
            end_date=self.today - timedelta(days=3),
            status=Leave.Status.EXTREME,
        )

        self.client.login(username='admin', password='admin123')
        response = self.client.get(f'/dashboard/employees/{self.employee.pk}/')

        leave_stats = response.context['leave_stats']
        self.assertEqual(leave_stats['approved'], 2)
        self.assertEqual(leave_stats['rejected'], 1)
        self.assertEqual(leave_stats['extreme'], 1)
        self.assertEqual(leave_stats['pending'], 0)
        self.assertEqual(leave_stats['cancelled'], 0)

    def test_employee_detail_shows_recent_leaves(self):
        """Employee detail shows recent leaves list."""
        leaves = []
        for i in range(5):
            leave = Leave.objects.create(
                employee=self.employee,
                start_date=self.today - timedelta(days=i),
                end_date=self.today - timedelta(days=i),
                status=Leave.Status.APPROVED,
            )
            leaves.append(leave)

        self.client.login(username='admin', password='admin123')
        response = self.client.get(f'/dashboard/employees/{self.employee.pk}/')

        recent_leaves = response.context['recent_leaves']
        self.assertEqual(len(recent_leaves), 5)
        # Should be ordered by created_at descending
        self.assertEqual(recent_leaves[0].id, leaves[-1].id)

    def test_employee_detail_requires_login(self):
        """Employee detail requires authentication."""
        response = self.client.get(f'/dashboard/employees/{self.employee.pk}/')

        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard/login/', response.url)

    def test_employee_detail_404_for_nonexistent(self):
        """Nonexistent employee returns 404."""
        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/employees/99999/')

        self.assertEqual(response.status_code, 404)


class AbsenceRecordingTests(TestCase):
    def setUp(self):
        """Set up test data for absence recording."""
        self.client = Client()
        self.user = User.objects.create_user(username='admin', password='admin123')

        self.location = Location.objects.create(
            name="Test Hospital",
            address="123 Main St",
            city="Testville",
            state="TX"
        )

        self.employee = Employee.objects.create(
            name="Test Employee",
            phone="+1555000001",
            employee_type=Employee.Type.PROVIDER,
            location=self.location,
            is_active=True,
        )

        self.today = timezone.localdate()

    def test_absence_form_loads(self):
        """Absence recording form loads successfully."""
        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/leaves/new/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('employees', response.context)

    def test_admin_can_record_absence(self):
        """Admin can record an absence for an employee."""
        self.client.login(username='admin', password='admin123')
        response = self.client.post('/dashboard/leaves/new/', {
            'employee_id': self.employee.id,
            'absence_date': str(self.today),
            'reason': 'No-show - emergency situation',
            'is_urgent': 'on',
        })

        # Should redirect to leaves page
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard/leaves/', response.url)

        # Leave should be created
        leave = Leave.objects.filter(
            employee=self.employee,
            start_date=self.today,
            end_date=self.today,
        ).first()

        self.assertIsNotNone(leave)
        self.assertEqual(leave.status, Leave.Status.APPROVED)
        self.assertEqual(leave.reason, 'No-show - emergency situation')
        self.assertIn('ADMIN RECORDED', leave.internal_note)
        self.assertIn('URGENT', leave.internal_note)

    def test_admin_can_record_absence_without_urgent(self):
        """Admin can record non-urgent absence."""
        self.client.login(username='admin', password='admin123')
        response = self.client.post('/dashboard/leaves/new/', {
            'employee_id': self.employee.id,
            'absence_date': str(self.today),
            'reason': 'Forgot to file leave',
            'is_urgent': '',  # Not urgent
        })

        self.assertEqual(response.status_code, 302)

        leave = Leave.objects.filter(
            employee=self.employee,
            start_date=self.today,
        ).first()

        self.assertIsNotNone(leave)
        self.assertNotIn('URGENT', leave.internal_note)

    def test_absence_cannot_be_future_date(self):
        """Cannot record absence for future dates."""
        self.client.login(username='admin', password='admin123')
        future_date = self.today + timedelta(days=1)

        response = self.client.post('/dashboard/leaves/new/', {
            'employee_id': self.employee.id,
            'absence_date': str(future_date),
            'reason': 'Future absence',
            'is_urgent': '',
        })

        # Should return form with error
        self.assertEqual(response.status_code, 200)
        self.assertIn('Cannot record absence for future dates', str(response.content))

        # No leave should be created
        self.assertFalse(Leave.objects.filter(
            employee=self.employee,
            start_date=future_date,
        ).exists())

    def test_absence_missing_fields_shows_error(self):
        """Missing required fields shows error."""
        self.client.login(username='admin', password='admin123')
        response = self.client.post('/dashboard/leaves/new/', {
            'employee_id': self.employee.id,
            'absence_date': str(self.today),
            # Missing reason
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('required', str(response.content).lower())

    def test_absence_creates_leave_visible_in_queue(self):
        """Recorded absence appears in leave queue."""
        self.client.login(username='admin', password='admin123')

        # Record absence
        self.client.post('/dashboard/leaves/new/', {
            'employee_id': self.employee.id,
            'absence_date': str(self.today),
            'reason': 'No-show',
            'is_urgent': 'on',
        })

        # Verify leave exists in database
        recorded_leave = Leave.objects.filter(
            employee=self.employee,
            start_date=self.today,
        ).first()

        self.assertIsNotNone(recorded_leave)
        self.assertIn('ADMIN RECORDED', recorded_leave.internal_note)
        self.assertEqual(recorded_leave.status, Leave.Status.APPROVED)

    def test_absence_affects_staffing_ratios(self):
        """Recorded absence affects active staffing counts."""
        from apps.shifts.models import Shift
        from apps.leaves.ratio import get_active_counts

        # Schedule provider for today
        Shift.objects.create(
            employee=self.employee,
            date=self.today,
            start_time='09:00',
            end_time='17:00',
        )

        # Create another provider for comparison
        provider2 = Employee.objects.create(
            name="Another Provider",
            phone="+1555000002",
            employee_type=Employee.Type.PROVIDER,
            location=self.location,
            is_active=True,
        )
        Shift.objects.create(
            employee=provider2,
            date=self.today,
            start_time='09:00',
            end_time='17:00',
        )

        # Before absence: 2 providers active
        p_before, _ = get_active_counts(self.location.id, self.today, self.today)
        self.assertEqual(p_before, 2)

        # Record absence
        self.client.login(username='admin', password='admin123')
        self.client.post('/dashboard/leaves/new/', {
            'employee_id': self.employee.id,
            'absence_date': str(self.today),
            'reason': 'No-show',
        })

        # After absence: 1 provider active
        p_after, _ = get_active_counts(self.location.id, self.today, self.today)
        self.assertEqual(p_after, 1)

    def test_absence_requires_login(self):
        """Absence form requires authentication."""
        response = self.client.get('/dashboard/leaves/new/')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard/login/', response.url)


class EmployeeLeaveInsightsTests(TestCase):
    def setUp(self):
        """Set up test data for employee insights."""
        self.client = Client()
        self.user = User.objects.create_user(username='admin', password='admin123')

        self.location = Location.objects.create(
            name="Test Hospital",
            address="123 Main St",
            city="Testville",
            state="TX"
        )

        self.employee = Employee.objects.create(
            name="Test Employee",
            phone="+1555000001",
            employee_type=Employee.Type.PROVIDER,
            location=self.location,
        )

        self.today = timezone.localdate()
        self.week_ago = self.today - timedelta(days=7)
        self.month_ago = self.today - timedelta(days=30)

    def test_employee_list_includes_leave_stats(self):
        """Employee list view includes leave statistics for each employee."""
        # Create some approved leaves
        Leave.objects.create(
            employee=self.employee,
            start_date=self.week_ago,
            end_date=self.week_ago,
            status=Leave.Status.APPROVED,
        )
        Leave.objects.create(
            employee=self.employee,
            start_date=self.month_ago,
            end_date=self.month_ago,
            status=Leave.Status.APPROVED,
        )

        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/employees/')

        self.assertEqual(response.status_code, 200)
        employees = response.context['employees']

        self.assertEqual(len(employees), 1)
        emp_item = employees[0]

        # Check that leave stats are present
        self.assertEqual(emp_item['leaves_week'], 1)
        self.assertEqual(emp_item['leaves_month'], 2)
        self.assertEqual(emp_item['leaves_total'], 2)

    def test_employee_leave_stats_exclude_rejected(self):
        """Employee leave stats only count APPROVED and EXTREME, not REJECTED/PENDING."""
        Leave.objects.create(
            employee=self.employee,
            start_date=self.week_ago,
            end_date=self.week_ago,
            status=Leave.Status.APPROVED,
        )
        Leave.objects.create(
            employee=self.employee,
            start_date=self.today,
            end_date=self.today,
            status=Leave.Status.REJECTED,
        )
        Leave.objects.create(
            employee=self.employee,
            start_date=self.today - timedelta(days=1),
            end_date=self.today - timedelta(days=1),
            status=Leave.Status.PENDING,
        )

        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/employees/')

        employees = response.context['employees']
        emp_item = employees[0]

        # Should only count the APPROVED leave
        self.assertEqual(emp_item['leaves_week'], 1)
        self.assertEqual(emp_item['leaves_total'], 1)

    def test_employee_leave_stats_include_extreme(self):
        """Employee leave stats include EXTREME status leaves."""
        Leave.objects.create(
            employee=self.employee,
            start_date=self.week_ago,
            end_date=self.week_ago,
            status=Leave.Status.EXTREME,
        )

        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/employees/')

        employees = response.context['employees']
        emp_item = employees[0]

        self.assertEqual(emp_item['leaves_week'], 1)
        self.assertEqual(emp_item['leaves_total'], 1)

    def test_employee_leave_stats_week_vs_month_boundaries(self):
        """Leave stats correctly respect week/month boundaries."""
        # Leave exactly 7 days ago (should count in week)
        Leave.objects.create(
            employee=self.employee,
            start_date=self.week_ago,
            end_date=self.week_ago,
            status=Leave.Status.APPROVED,
        )
        # Leave exactly 30 days ago (should count in month but not week)
        Leave.objects.create(
            employee=self.employee,
            start_date=self.month_ago,
            end_date=self.month_ago,
            status=Leave.Status.APPROVED,
        )

        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/employees/')

        employees = response.context['employees']
        emp_item = employees[0]

        self.assertEqual(emp_item['leaves_week'], 1)
        self.assertEqual(emp_item['leaves_month'], 2)

    def test_employee_list_with_filters_shows_stats(self):
        """Employee stats are shown even when filters are applied."""
        Leave.objects.create(
            employee=self.employee,
            start_date=self.week_ago,
            end_date=self.week_ago,
            status=Leave.Status.APPROVED,
        )

        self.client.login(username='admin', password='admin123')
        response = self.client.get(f'/dashboard/employees/?type=PROVIDER&location={self.location.id}')

        self.assertEqual(response.status_code, 200)
        employees = response.context['employees']
        emp_item = employees[0]

        self.assertEqual(emp_item['leaves_week'], 1)

    def test_multiple_employees_have_independent_stats(self):
        """Multiple employees have independent leave statistics."""
        employee2 = Employee.objects.create(
            name="Another Employee",
            phone="+1555000002",
            employee_type=Employee.Type.MEDICAL_ASSISTANT,
            location=self.location,
        )

        # First employee: 1 leave this week
        Leave.objects.create(
            employee=self.employee,
            start_date=self.week_ago,
            end_date=self.week_ago,
            status=Leave.Status.APPROVED,
        )

        # Second employee: 2 leaves this week
        Leave.objects.create(
            employee=employee2,
            start_date=self.week_ago,
            end_date=self.week_ago,
            status=Leave.Status.APPROVED,
        )
        Leave.objects.create(
            employee=employee2,
            start_date=self.today,
            end_date=self.today,
            status=Leave.Status.APPROVED,
        )

        self.client.login(username='admin', password='admin123')
        response = self.client.get('/dashboard/employees/')

        employees = response.context['employees']
        self.assertEqual(len(employees), 2)

        # Find each employee in the response
        emp1_item = next(e for e in employees if e['emp'].id == self.employee.id)
        emp2_item = next(e for e in employees if e['emp'].id == employee2.id)

        self.assertEqual(emp1_item['leaves_week'], 1)
        self.assertEqual(emp2_item['leaves_week'], 2)
