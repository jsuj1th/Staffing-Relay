"""
Ratio engine for Provider:MA staffing at a location.

Ratio tiers (Providers:MAs):
  Ideal   — providers <= MAs          (e.g. 3:4, 3:3)
  Warning — providers > MAs           (e.g. 3:2 extreme case, still allowed)
  Reject  — providers * 2 > MAs * 3  (worse than 3:2)

Integer arithmetic is used throughout to avoid float drift at the 3:2 boundary.
"""
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


def get_active_counts(location_id: int, start_date: date, end_date: date, exclude_employee_id: int = None):
    """
    Returns (provider_count, ma_count) of employees NOT on APPROVED/EXTREME leave
    for any day in the given range at the given location.
    """
    from apps.leaves.models import Leave
    from apps.accounts.models import Employee

    # Employees at this location on leave during the date range
    on_leave_qs = Leave.objects.filter(
        employee__location_id=location_id,
        status__in=[Leave.Status.APPROVED, Leave.Status.EXTREME],
        start_date__lte=end_date,
        end_date__gte=start_date,
    )
    if exclude_employee_id is not None:
        on_leave_qs = on_leave_qs.exclude(employee_id=exclude_employee_id)

    on_leave_ids = set(on_leave_qs.values_list("employee_id", flat=True))

    base_qs = Employee.objects.filter(location_id=location_id, is_active=True)

    providers = base_qs.filter(
        employee_type=Employee.Type.PROVIDER
    ).exclude(id__in=on_leave_ids).count()

    mas = base_qs.filter(
        employee_type=Employee.Type.MEDICAL_ASSISTANT
    ).exclude(id__in=on_leave_ids).count()

    logger.debug(
        "get_active_counts: location=%s start=%s end=%s providers=%d mas=%d",
        location_id, start_date, end_date, providers, mas,
    )
    return providers, mas


def _ratio_outcome(p_after: int, ma_after: int, p_before: int, ma_before: int):
    """Determine status and employee-facing message for a given staffing count."""
    from apps.leaves.models import Leave

    if p_after <= 0 or ma_after <= 0:
        return (
            Leave.Status.REJECTED,
            "Sorry, your leave cannot be approved — it would leave the location with no coverage. Please contact your manager.",
            {"providers": p_before, "mas": ma_before},
            {"providers": p_after, "mas": ma_after},
        )

    # p/ma > 3/2  ⟺  p*2 > ma*3
    if p_after * 2 > ma_after * 3:
        return (
            Leave.Status.REJECTED,
            "Sorry, your leave cannot be approved due to staffing requirements. Please contact your manager.",
            {"providers": p_before, "mas": ma_before},
            {"providers": p_after, "mas": ma_after},
        )

    if p_after > ma_after:
        # Between 1:1 and 3:2 — extreme, allowed but flagged
        return (
            Leave.Status.EXTREME,
            "Your leave has been noted. Please coordinate with your team to ensure coverage.",
            {"providers": p_before, "mas": ma_before},
            {"providers": p_after, "mas": ma_after},
        )

    # p_after <= ma_after — normal or ideal
    return (
        Leave.Status.APPROVED,
        "Your leave request has been approved. Have a great time off!",
        {"providers": p_before, "mas": ma_before},
        {"providers": p_after, "mas": ma_after},
    )


def evaluate_leave(employee, start_date: date, end_date: date):
    """
    Evaluate whether a leave request can be granted.
    Uses worst-day-wins: evaluates every calendar day in the range and returns
    the most severe outcome across all days.

    Returns: (status, employee_message, ratio_before, ratio_after)
    """
    from apps.accounts.models import Employee
    from apps.leaves.models import Leave

    logger.debug(
        "evaluate_leave: employee=%s start=%s end=%s",
        employee.name, start_date, end_date,
    )

    # FRONT_DESK and MANAGEMENT skip ratio checks entirely
    if employee.employee_type in (Employee.Type.FRONT_DESK, Employee.Type.MANAGEMENT):
        return (
            Leave.Status.APPROVED,
            "Your leave request has been approved. Have a great time off!",
            None,
            None,
        )

    loc_id = employee.location_id
    is_provider = employee.employee_type == Employee.Type.PROVIDER

    # Evaluate every day in the range (worst-day-wins)
    worst_status = None
    worst_result = None
    status_order = {
        Leave.Status.REJECTED: 3,
        Leave.Status.EXTREME: 2,
        Leave.Status.APPROVED: 1,
    }

    current_day = start_date
    while current_day <= end_date:
        logger.debug(
            "evaluate_leave: checking day=%s employee=%s",
            current_day, employee.name,
        )
        p_before, ma_before = get_active_counts(loc_id, current_day, current_day, exclude_employee_id=employee.id)
        p_after = p_before - (1 if is_provider else 0)
        ma_after = ma_before - (0 if is_provider else 1)

        result = _ratio_outcome(p_after, ma_after, p_before, ma_before)
        day_status = result[0]

        if worst_status is None or status_order.get(day_status, 0) > status_order.get(worst_status, 0):
            worst_status = day_status
            worst_result = result

        if worst_status == Leave.Status.REJECTED:
            break  # Can't get worse, stop early

        current_day += timedelta(days=1)

    logger.info(
        "Leave decision: employee=%s status=%s ratio_before=%s ratio_after=%s",
        employee.name, worst_result[0], worst_result[2], worst_result[3],
    )
    return worst_result
