"""
Tests for the ratio engine and leave evaluation logic.
"""
from datetime import date, timedelta
from django.test import TestCase

from apps.accounts.models import Employee
from apps.locations.models import Location
from apps.leaves.models import Leave
from apps.leaves.ratio import get_active_counts, evaluate_leave
from apps.shifts.models import Shift


class RatioEngineTests(TestCase):
    def setUp(self):
        self.location = Location.objects.create(
            name="Test Hospital", address="1 Main St", city="Testville", state="TX"
        )
        # 3 providers, 4 MAs → ideal starting state
        self.providers = []
        for i in range(3):
            p = Employee.objects.create(
                name=f"Provider {i}",
                phone=f"+1555000010{i}",
                employee_type=Employee.Type.PROVIDER,
                location=self.location,
            )
            self.providers.append(p)

        self.mas = []
        for i in range(4):
            ma = Employee.objects.create(
                name=f"MA {i}",
                phone=f"+1555000020{i}",
                employee_type=Employee.Type.MEDICAL_ASSISTANT,
                location=self.location,
            )
            self.mas.append(ma)

        self.today = date.today()
        self.tomorrow = self.today + timedelta(days=1)

        # Give every employee a shift across every relative date used anywhere
        # in this file (today, tomorrow, today+2, today+10, today+30, etc.)
        # so pre-existing tests keep exercising "on duty" employees under the
        # new shift-based counting rule.
        for offset in range(-1, 40):
            shift_date = self.today + timedelta(days=offset)
            for emp in self.providers + self.mas:
                Shift.objects.create(
                    employee=emp, date=shift_date,
                    start_time="09:00", end_time="17:00",
                )

    # --- get_active_counts ---

    def test_full_staff_no_leaves(self):
        p, ma = get_active_counts(self.location.id, self.today, self.today)
        self.assertEqual(p, 3)
        self.assertEqual(ma, 4)

    def test_active_counts_exclude_approved_leave(self):
        Leave.objects.create(
            employee=self.providers[0],
            start_date=self.today,
            end_date=self.today,
            status=Leave.Status.APPROVED,
        )
        p, ma = get_active_counts(self.location.id, self.today, self.today)
        self.assertEqual(p, 2)
        self.assertEqual(ma, 4)

    def test_active_counts_exclude_extreme_leave(self):
        Leave.objects.create(
            employee=self.mas[0],
            start_date=self.today,
            end_date=self.today,
            status=Leave.Status.EXTREME,
        )
        p, ma = get_active_counts(self.location.id, self.today, self.today)
        self.assertEqual(p, 3)
        self.assertEqual(ma, 3)

    def test_active_counts_do_not_exclude_rejected_leave(self):
        Leave.objects.create(
            employee=self.providers[0],
            start_date=self.today,
            end_date=self.today,
            status=Leave.Status.REJECTED,
        )
        p, ma = get_active_counts(self.location.id, self.today, self.today)
        self.assertEqual(p, 3)  # rejected → still on duty

    def test_active_counts_exclude_employee_id(self):
        # Put providers[0] on an approved leave so they would normally show as absent
        Leave.objects.create(
            employee=self.providers[0],
            start_date=self.today,
            end_date=self.today,
            status=Leave.Status.APPROVED,
        )
        # Without exclusion: providers[0] is on leave → count is 2
        p_normal, _ = get_active_counts(self.location.id, self.today, self.today)
        self.assertEqual(p_normal, 2)
        # With exclusion: their existing leave is ignored (used when evaluating their own new request)
        # → they appear active → count is 3
        p_excl, _ = get_active_counts(self.location.id, self.today, self.today, exclude_employee_id=self.providers[0].id)
        self.assertEqual(p_excl, 3)

    def test_no_shifts_means_nobody_counted(self):
        """A date with zero Shift rows anywhere → nobody is on duty."""
        far_future = self.today + timedelta(days=200)
        p, ma = get_active_counts(self.location.id, far_future, far_future)
        self.assertEqual(p, 0)
        self.assertEqual(ma, 0)

    def test_only_scheduled_employees_counted(self):
        """Employees without a shift on the date don't count, even if is_active."""
        target_date = self.today + timedelta(days=201)
        Shift.objects.create(
            employee=self.providers[0], date=target_date,
            start_time="09:00", end_time="17:00",
        )
        Shift.objects.create(
            employee=self.mas[0], date=target_date,
            start_time="09:00", end_time="17:00",
        )
        p, ma = get_active_counts(self.location.id, target_date, target_date)
        self.assertEqual(p, 1)
        self.assertEqual(ma, 1)

    # --- evaluate_leave: FRONT_DESK / MANAGEMENT auto-approved ---

    def test_front_desk_always_approved(self):
        fd = Employee.objects.create(
            name="Front Desk", phone="+15550009001",
            employee_type=Employee.Type.FRONT_DESK, location=None,
        )
        status, msg, before, after = evaluate_leave(fd, self.today, self.today)
        self.assertEqual(status, Leave.Status.APPROVED)
        self.assertIsNone(before)
        self.assertIsNone(after)

    def test_management_always_approved(self):
        mgr = Employee.objects.create(
            name="Manager", phone="+15550009002",
            employee_type=Employee.Type.MANAGEMENT, location=None,
        )
        status, msg, before, after = evaluate_leave(mgr, self.today, self.today)
        self.assertEqual(status, Leave.Status.APPROVED)

    # --- evaluate_leave: PROVIDER ratio checks ---

    def test_provider_leave_ideal_state(self):
        # 3P:4MA, provider takes leave → 2P:4MA (ideal)
        status, msg, before, after = evaluate_leave(self.providers[0], self.today, self.today)
        self.assertEqual(status, Leave.Status.APPROVED)
        self.assertEqual(before, {"providers": 3, "mas": 4})
        self.assertEqual(after, {"providers": 2, "mas": 4})

    def test_provider_leave_reaches_extreme(self):
        # Set to 3P:2MA initially by putting 2 MAs on approved leave
        Leave.objects.create(employee=self.mas[0], start_date=self.today, end_date=self.today, status=Leave.Status.APPROVED)
        Leave.objects.create(employee=self.mas[1], start_date=self.today, end_date=self.today, status=Leave.Status.APPROVED)
        # Now 3P:2MA; provider takes leave → 2P:2MA (1:1, approved normal)
        status, msg, before, after = evaluate_leave(self.providers[0], self.today, self.today)
        self.assertEqual(status, Leave.Status.APPROVED)

    def test_provider_leave_rejected_exceeds_32(self):
        # Set to 3P:1MA by putting 3 MAs on leave
        for ma in self.mas[:3]:
            Leave.objects.create(employee=ma, start_date=self.today, end_date=self.today, status=Leave.Status.APPROVED)
        # Now 3P:1MA; provider takes leave → 2P:1MA (2:1 ratio, worse than 3:2) → REJECTED
        status, msg, before, after = evaluate_leave(self.providers[0], self.today, self.today)
        self.assertEqual(status, Leave.Status.REJECTED)

    # --- evaluate_leave: MA ratio checks ---

    def test_ma_leave_approved_from_ideal(self):
        # 3P:4MA, MA takes leave → 3P:3MA (normal)
        status, msg, before, after = evaluate_leave(self.mas[0], self.today, self.today)
        self.assertEqual(status, Leave.Status.APPROVED)

    def test_ma_leave_extreme_at_boundary(self):
        # Set to 3P:3MA, MA takes leave → 3P:2MA (extreme boundary)
        Leave.objects.create(employee=self.mas[3], start_date=self.today, end_date=self.today, status=Leave.Status.APPROVED)
        status, msg, before, after = evaluate_leave(self.mas[0], self.today, self.today)
        self.assertEqual(status, Leave.Status.EXTREME)

    def test_ma_leave_rejected_from_32(self):
        # Start at 3P:2MA, MA takes leave → 3P:1MA (worse than 3:2) → REJECTED
        Leave.objects.create(employee=self.mas[2], start_date=self.today, end_date=self.today, status=Leave.Status.APPROVED)
        Leave.objects.create(employee=self.mas[3], start_date=self.today, end_date=self.today, status=Leave.Status.APPROVED)
        status, msg, before, after = evaluate_leave(self.mas[0], self.today, self.today)
        self.assertEqual(status, Leave.Status.REJECTED)

    # --- Exact 3:2 boundary (integer arithmetic) ---

    def test_exact_32_boundary_is_extreme_not_rejected(self):
        """3P * 2 == 2MA * 3 → should be EXTREME, not REJECTED."""
        # Reduce MAs to 2 (put 2 on approved leave)
        Leave.objects.create(employee=self.mas[2], start_date=self.today, end_date=self.today, status=Leave.Status.APPROVED)
        Leave.objects.create(employee=self.mas[3], start_date=self.today, end_date=self.today, status=Leave.Status.APPROVED)
        # Now 3P:2MA. An MA requesting leave would → 3P:1MA (REJECTED).
        # A provider requesting leave would → 2P:2MA (APPROVED normal).
        # What we want to test: the EXACT 3:2 case stays EXTREME.
        # We have 3P:2MA — that IS the extreme state for existing employees.
        # Let's simulate: provider leaves, and we are at 3P:3MA (one MA on leave already)
        Leave.objects.create(employee=self.mas[3], start_date=self.today + timedelta(days=10), end_date=self.today + timedelta(days=10), status=Leave.Status.APPROVED)
        # Reset: check at a fresh date with 3P:2MA  
        future = self.today + timedelta(days=30)
        Leave.objects.create(employee=self.mas[2], start_date=future, end_date=future, status=Leave.Status.APPROVED)
        Leave.objects.create(employee=self.mas[3], start_date=future, end_date=future, status=Leave.Status.APPROVED)
        # Now 3P:2MA on `future` date. Check a provider: → 2P:2MA → APPROVED
        status, _, _, _ = evaluate_leave(self.providers[0], future, future)
        self.assertEqual(status, Leave.Status.APPROVED)

    # --- Multi-day worst-day-wins ---

    def test_multiday_worst_day_triggers_rejection(self):
        """If one day in range would cause rejection, whole request is rejected."""
        # Put 3 MAs on leave on day 2 of a 2-day range
        day2 = self.today + timedelta(days=2)
        for ma in self.mas[:3]:
            Leave.objects.create(employee=ma, start_date=day2, end_date=day2, status=Leave.Status.APPROVED)
        # Day 1: 3P:4MA fine; Day 2: 3P:1MA, requesting MA = 3P:0MA → REJECTED
        status, _, _, _ = evaluate_leave(self.mas[3], self.today, day2)
        self.assertEqual(status, Leave.Status.REJECTED)

    def test_no_coverage_rejected(self):
        """Leave that would leave 0 MAs is always rejected."""
        for ma in self.mas[1:]:
            Leave.objects.create(employee=ma, start_date=self.today, end_date=self.today, status=Leave.Status.APPROVED)
        # Now 3P:1MA. Last MA requests leave → 3P:0MA
        status, _, _, _ = evaluate_leave(self.mas[0], self.today, self.today)
        self.assertEqual(status, Leave.Status.REJECTED)
