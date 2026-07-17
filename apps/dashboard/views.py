import json
import logging
from datetime import date, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Q

from apps.accounts.models import Employee
from apps.locations.models import Location, EmployeeLocation
from apps.leaves.models import Leave
from apps.messaging.models import SmsLog
from apps.messaging.sms import send_sms
from apps.leaves.ratio import get_active_counts
from apps.shifts.models import Shift

logger = logging.getLogger(__name__)


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:overview")
    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect(request.GET.get("next", "dashboard:overview"))
        messages.error(request, "Invalid username or password.")
    return render(request, "registration/login.html")


def logout_view(request):
    logout(request)
    return redirect("dashboard:login")


@login_required
def overview(request):
    logger.debug("overview: user=%s", request.user)
    today = timezone.localdate()
    locations = Location.objects.all()
    location_data = []
    for loc in locations:
        p, ma = get_active_counts(loc.id, today, today)
        status = "good"
        if ma == 0 or p * 2 > ma * 3:
            status = "critical"
        elif p > ma:
            status = "warning"
        pending_count = Leave.objects.filter(
            employee__location=loc,
            status=Leave.Status.PENDING,
        ).count()
        location_data.append({
            "location": loc,
            "providers": p,
            "mas": ma,
            "status": status,
            "pending_count": pending_count,
        })

    recent_leaves = Leave.objects.select_related("employee", "employee__location").order_by("-created_at")[:10]
    return render(request, "dashboard/overview.html", {
        "location_data": location_data,
        "recent_leaves": recent_leaves,
        "today": today,
    })


@login_required
def employee_list(request):
    qs = Employee.objects.select_related("location").all()
    type_filter = request.GET.get("type", "")
    location_filter = request.GET.get("location", "")
    if type_filter:
        qs = qs.filter(employee_type=type_filter)
    if location_filter:
        qs = qs.filter(location_id=location_filter)

    today = timezone.localdate()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Add leave statistics to each employee
    employees_with_stats = []
    for emp in qs:
        leaves_week = Leave.objects.filter(
            employee=emp,
            end_date__gte=week_ago,
            start_date__lte=today,
            status__in=[Leave.Status.APPROVED, Leave.Status.EXTREME],
        ).count()
        leaves_month = Leave.objects.filter(
            employee=emp,
            end_date__gte=month_ago,
            start_date__lte=today,
            status__in=[Leave.Status.APPROVED, Leave.Status.EXTREME],
        ).count()
        leaves_total = Leave.objects.filter(
            employee=emp,
            status__in=[Leave.Status.APPROVED, Leave.Status.EXTREME],
        ).count()
        employees_with_stats.append({
            "emp": emp,
            "leaves_week": leaves_week,
            "leaves_month": leaves_month,
            "leaves_total": leaves_total,
        })

    locations = Location.objects.all()
    return render(request, "dashboard/employees.html", {
        "employees": employees_with_stats,
        "locations": locations,
        "type_filter": type_filter,
        "location_filter": location_filter,
        "employee_types": Employee.Type.choices,
    })


@login_required
def employee_create(request):
    locations = Location.objects.all()
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        phone = request.POST.get("phone", "").strip()
        emp_type = request.POST.get("employee_type", "")
        location_id = request.POST.get("location_id") or None
        shared_location_ids = request.POST.getlist("shared_location_ids")

        if not name or not phone or not emp_type:
            messages.error(request, "Name, phone, and type are required.")
            return render(request, "dashboard/employee_form.html", {"locations": locations, "action": "Add"})

        if Employee.objects.filter(phone=phone).exists():
            messages.error(request, f"Phone number {phone} is already registered.")
            return render(request, "dashboard/employee_form.html", {"locations": locations, "action": "Add"})

        is_location_specific = emp_type in (Employee.Type.PROVIDER, Employee.Type.MEDICAL_ASSISTANT)
        if is_location_specific and not location_id:
            messages.error(request, "Providers and Medical Assistants must be assigned to a location.")
            return render(request, "dashboard/employee_form.html", {"locations": locations, "action": "Add"})

        emp = Employee.objects.create(
            name=name,
            phone=phone,
            employee_type=emp_type,
            location_id=location_id if is_location_specific else None,
        )
        logger.info("Employee created: id=%d name=%s", emp.id, emp.name)

        # For shared employees, create EmployeeLocation records
        if not is_location_specific and shared_location_ids:
            for i, loc_id in enumerate(shared_location_ids):
                EmployeeLocation.objects.create(
                    employee=emp,
                    location_id=loc_id,
                    is_primary=(i == 0),
                )

        messages.success(request, f"Employee {emp.name} added successfully.")
        return redirect("dashboard:employees")

    return render(request, "dashboard/employee_form.html", {"locations": locations, "action": "Add"})


@login_required
def employee_edit(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    locations = Location.objects.all()
    current_shared = list(emp.employee_locations.values_list("location_id", flat=True))

    if request.method == "POST":
        emp.name = request.POST.get("name", emp.name).strip()
        phone = request.POST.get("phone", emp.phone).strip()
        emp_type = request.POST.get("employee_type", emp.employee_type)
        location_id = request.POST.get("location_id") or None
        shared_location_ids = request.POST.getlist("shared_location_ids")
        emp.is_active = request.POST.get("is_active") == "on"

        if Employee.objects.filter(phone=phone).exclude(pk=pk).exists():
            messages.error(request, f"Phone number {phone} is already used by another employee.")
        else:
            emp.phone = phone
            emp.employee_type = emp_type
            is_location_specific = emp_type in (Employee.Type.PROVIDER, Employee.Type.MEDICAL_ASSISTANT)
            emp.location_id = location_id if is_location_specific else None
            emp.save()
            logger.info("Employee updated: id=%d name=%s", emp.id, emp.name)

            # Update shared locations
            if not is_location_specific:
                emp.employee_locations.all().delete()
                for i, loc_id in enumerate(shared_location_ids):
                    EmployeeLocation.objects.get_or_create(
                        employee=emp,
                        location_id=loc_id,
                        defaults={"is_primary": i == 0},
                    )

            messages.success(request, f"Employee {emp.name} updated.")
            return redirect("dashboard:employees")

    return render(request, "dashboard/employee_form.html", {
        "employee": emp,
        "locations": locations,
        "current_shared": current_shared,
        "action": "Edit",
    })


@login_required
def employee_toggle_active(request, pk):
    """Soft-delete: deactivate an active employee (or restore an inactive one).

    Deactivating drops them from ratio counts, shift assignment, and leave
    dropdowns while preserving all leave/SMS history — reversible via restore.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    emp = get_object_or_404(Employee, pk=pk)
    emp.is_active = not emp.is_active
    emp.save(update_fields=["is_active"])
    action = "restored" if emp.is_active else "removed"
    logger.info("Employee %s: id=%d name=%s by=%s", action, emp.id, emp.name, request.user)
    messages.success(request, f"{emp.name} {action}.")
    return redirect("dashboard:employees")


@login_required
def leave_list(request):
    qs = Leave.objects.select_related("employee", "employee__location")
    status_filter = request.GET.get("status", "")
    location_filter = request.GET.get("location", "")
    period_filter = request.GET.get("period", "")

    if status_filter:
        qs = qs.filter(status=status_filter)
    if location_filter:
        qs = qs.filter(employee__location_id=location_filter)

    today = timezone.localdate()
    if period_filter == "week":
        cutoff = today - timedelta(days=7)
        qs = qs.filter(end_date__gte=cutoff, start_date__lte=today)
    elif period_filter == "month":
        cutoff = today - timedelta(days=30)
        qs = qs.filter(end_date__gte=cutoff, start_date__lte=today)

    locations = Location.objects.all()
    return render(request, "dashboard/leaves.html", {
        "leaves": qs.order_by("-created_at")[:200],
        "locations": locations,
        "status_filter": status_filter,
        "location_filter": location_filter,
        "period_filter": period_filter,
        "leave_statuses": Leave.Status.choices,
    })


@login_required
def leave_decision(request, pk):
    """Manager manually approves or rejects a leave."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    leave = get_object_or_404(Leave, pk=pk)
    action = request.POST.get("action")
    note = request.POST.get("note", "")

    if action not in ("approve", "reject"):
        messages.error(request, "Invalid action.")
        return redirect("dashboard:leaves")

    old_status = leave.status
    if action == "approve":
        leave.status = Leave.Status.APPROVED
    else:
        leave.status = Leave.Status.REJECTED

    if note:
        leave.internal_note = note
    leave.approved_by = request.user
    leave.save()
    logger.info("Leave action: id=%d action=%s by=%s", leave.id, action, request.user)

    # Notify employee via SMS using new notification system
    from apps.messaging.notifications import notify_leave_approved, notify_leave_rejected

    if action == "approve":
        notify_leave_approved(leave, send_immediately=True)
    else:
        notify_leave_rejected(leave, send_immediately=True)

    messages.success(request, f"Leave {leave.status.lower()} and employee notified via SMS.")
    return redirect("dashboard:leaves")


@login_required
def sms_log_list(request):
    logs = SmsLog.objects.select_related("employee", "leave").order_by("-created_at")[:300]
    return render(request, "dashboard/sms_logs.html", {"logs": logs})


@login_required
def location_detail(request, pk):
    location = get_object_or_404(Location, pk=pk)
    today = timezone.localdate()
    p, ma = get_active_counts(location.id, today, today)

    providers = Employee.objects.filter(location=location, employee_type=Employee.Type.PROVIDER, is_active=True)
    mas = Employee.objects.filter(location=location, employee_type=Employee.Type.MEDICAL_ASSISTANT, is_active=True)
    shared_emps = EmployeeLocation.objects.filter(location=location).select_related("employee")
    recent_leaves = Leave.objects.filter(employee__location=location).select_related("employee").order_by("-created_at")[:20]

    return render(request, "dashboard/location_detail.html", {
        "location": location,
        "providers": providers,
        "mas": mas,
        "shared_emps": shared_emps,
        "recent_leaves": recent_leaves,
        "active_providers": p,
        "active_mas": ma,
        "today": today,
    })


@login_required
def shift_day(request):
    today = timezone.localdate()
    location_id = request.GET.get("location", "")
    date_str = request.GET.get("date", "")
    try:
        selected_date = date.fromisoformat(date_str) if date_str else today
    except ValueError:
        messages.error(request, "Invalid date; showing today instead.")
        selected_date = today

    locations = Location.objects.all()
    selected_location = None
    employees = Employee.objects.none()
    shifts_by_employee = {}

    if location_id:
        try:
            selected_location = get_object_or_404(Location, pk=int(location_id))
        except ValueError:
            selected_location = None
    if selected_location:
        employees = Employee.objects.filter(
            location=selected_location,
            employee_type__in=[Employee.Type.PROVIDER, Employee.Type.MEDICAL_ASSISTANT],
            is_active=True,
        ).order_by("name")
        day_shifts = Shift.objects.filter(
            employee__in=employees, date=selected_date
        ).select_related("employee")
        for shift in day_shifts:
            shifts_by_employee.setdefault(shift.employee_id, []).append(shift)

    rows = [
        {"employee": emp, "shifts": shifts_by_employee.get(emp.id, [])}
        for emp in employees
    ]

    return render(request, "dashboard/shifts.html", {
        "locations": locations,
        "selected_location": selected_location,
        "selected_date": selected_date,
        "rows": rows,
        "today": today,
    })


@login_required
def shift_create(request):
    locations = Location.objects.all()
    preselect_location_id = request.GET.get("location", "")
    preselect_date = request.GET.get("date", "")
    employees = Employee.objects.filter(
        employee_type__in=[Employee.Type.PROVIDER, Employee.Type.MEDICAL_ASSISTANT],
        is_active=True,
    ).select_related("location").order_by("name")

    if request.method == "POST":
        employee_id = request.POST.get("employee_id")
        shift_date_str = request.POST.get("date", "")
        start_time = request.POST.get("start_time", "")
        end_time = request.POST.get("end_time", "")

        if not (employee_id and shift_date_str and start_time and end_time):
            messages.error(request, "Employee, date, start time, and end time are required.")
            return render(request, "dashboard/shift_form.html", {
                "locations": locations, "employees": employees, "action": "Add",
                "preselect_location_id": preselect_location_id,
                "preselect_date": preselect_date,
            })

        try:
            repeat_weeks = int(request.POST.get("repeat_weeks") or 0)
        except ValueError:
            messages.error(request, "Repeat weeks must be a number.")
            return render(request, "dashboard/shift_form.html", {
                "locations": locations, "employees": employees, "action": "Add",
                "preselect_location_id": preselect_location_id,
                "preselect_date": preselect_date,
            })
        repeat_weeks = min(max(repeat_weeks, 0), 52)

        try:
            shift_date = date.fromisoformat(shift_date_str)
        except ValueError:
            messages.error(request, "Invalid date.")
            return render(request, "dashboard/shift_form.html", {
                "locations": locations, "employees": employees, "action": "Add",
                "preselect_location_id": preselect_location_id,
                "preselect_date": preselect_date,
            })

        employee = get_object_or_404(Employee, pk=employee_id)

        Shift.objects.create(
            employee=employee, date=shift_date,
            start_time=start_time, end_time=end_time,
            created_by=request.user,
        )
        for week in range(1, repeat_weeks + 1):
            Shift.objects.create(
                employee=employee, date=shift_date + timedelta(weeks=week),
                start_time=start_time, end_time=end_time,
                created_by=request.user,
            )

        logger.info("Shift created: employee=%s date=%s repeat_weeks=%d", employee.name, shift_date, repeat_weeks)

        # Queue SMS notifications for shift assignments
        from apps.messaging.notifications import notify_shift_assigned

        shift = Shift.objects.get(employee=employee, date=shift_date)
        notify_shift_assigned(shift, send_immediately=False)  # Batch in 1 hour

        if repeat_weeks:
            for week in range(1, repeat_weeks + 1):
                repeated_shift = Shift.objects.get(
                    employee=employee,
                    date=shift_date + timedelta(weeks=week),
                )
                notify_shift_assigned(repeated_shift, send_immediately=False)

        messages.success(request, f"Shift added for {employee.name}" + (f" (repeated {repeat_weeks} weeks)" if repeat_weeks else "") + ". SMS notification queued.")
        return redirect(f"/dashboard/shifts/?location={employee.location_id}&date={shift_date_str}")

    return render(request, "dashboard/shift_form.html", {
        "locations": locations, "employees": employees, "action": "Add",
        "preselect_location_id": preselect_location_id,
        "preselect_date": preselect_date,
    })


@login_required
def shift_edit(request, pk):
    shift = get_object_or_404(Shift, pk=pk)

    if request.method == "POST":
        try:
            shift.date = date.fromisoformat(request.POST.get("date", str(shift.date)))
        except ValueError:
            messages.error(request, "Invalid date.")
            return render(request, "dashboard/shift_form.html", {
                "shift": shift, "action": "Edit",
                "locations": Location.objects.all(),
            })
        shift.start_time = request.POST.get("start_time", shift.start_time)
        shift.end_time = request.POST.get("end_time", shift.end_time)
        shift.save()
        logger.info("Shift updated: id=%d employee=%s", shift.id, shift.employee.name)
        messages.success(request, "Shift updated.")
        return redirect(f"/dashboard/shifts/?location={shift.employee.location_id}&date={shift.date}")

    return render(request, "dashboard/shift_form.html", {
        "shift": shift, "action": "Edit",
        "locations": Location.objects.all(),
    })


@login_required
def shift_delete(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    shift = get_object_or_404(Shift, pk=pk)
    location_id = shift.employee.location_id
    shift_date = shift.date
    employee_name = shift.employee.name
    shift.delete()
    logger.info("Shift deleted: employee=%s date=%s", employee_name, shift_date)
    messages.success(request, f"Shift removed for {employee_name}.")
    return redirect(f"/dashboard/shifts/?location={location_id}&date={shift_date}")


@login_required
def absence_create(request):
    """Admin manually records an employee absence (no-show, emergency, etc)."""
    locations = Location.objects.all()
    employees = Employee.objects.filter(is_active=True).select_related("location").order_by("name")

    if request.method == "POST":
        employee_id = request.POST.get("employee_id")
        absence_date_str = request.POST.get("absence_date", "")
        reason = request.POST.get("reason", "").strip()
        is_urgent = request.POST.get("is_urgent") == "on"

        if not (employee_id and absence_date_str and reason):
            messages.error(request, "Employee, date, and reason are required.")
            return render(request, "dashboard/absence_form.html", {
                "locations": locations,
                "employees": employees,
            })

        try:
            absence_date = date.fromisoformat(absence_date_str)
        except ValueError:
            messages.error(request, "Invalid date.")
            return render(request, "dashboard/absence_form.html", {
                "locations": locations,
                "employees": employees,
            })

        if absence_date > timezone.localdate():
            messages.error(request, "Cannot record absence for future dates.")
            return render(request, "dashboard/absence_form.html", {
                "locations": locations,
                "employees": employees,
            })

        employee = get_object_or_404(Employee, pk=employee_id)

        # Create a leave record marked as "unplanned absence"
        # Use internal_note to track that admin recorded this
        leave = Leave.objects.create(
            employee=employee,
            start_date=absence_date,
            end_date=absence_date,
            reason=reason,
            status=Leave.Status.APPROVED,  # Auto-approved since admin recorded it
            internal_note=f"[ADMIN RECORDED] {'URGENT: ' if is_urgent else ''}Absence recorded by {request.user.username}",
            approved_by=request.user,
        )

        logger.info("Absence recorded: employee=%s date=%s urgent=%s by=%s", employee.name, absence_date, is_urgent, request.user)
        messages.success(request, f"Absence recorded for {employee.name} on {absence_date}.")
        return redirect("dashboard:leaves")

    return render(request, "dashboard/absence_form.html", {
        "locations": locations,
        "employees": employees,
    })


@login_required
def employee_detail(request, pk):
    """Employee profile with leave insights and history."""
    employee = get_object_or_404(Employee, pk=pk)
    today = timezone.localdate()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Leave statistics
    leaves_approved = Leave.objects.filter(
        employee=employee,
        status__in=[Leave.Status.APPROVED, Leave.Status.EXTREME],
    )

    leaves_week = leaves_approved.filter(
        end_date__gte=week_ago,
        start_date__lte=today,
    ).count()

    leaves_month = leaves_approved.filter(
        end_date__gte=month_ago,
        start_date__lte=today,
    ).count()

    leaves_total = leaves_approved.count()

    # Recent leaves (last 30 days)
    recent_leaves = Leave.objects.filter(employee=employee).order_by("-created_at")[:30]

    # Leave breakdown by status
    leave_stats = {
        "approved": Leave.objects.filter(employee=employee, status=Leave.Status.APPROVED).count(),
        "extreme": Leave.objects.filter(employee=employee, status=Leave.Status.EXTREME).count(),
        "rejected": Leave.objects.filter(employee=employee, status=Leave.Status.REJECTED).count(),
        "pending": Leave.objects.filter(employee=employee, status=Leave.Status.PENDING).count(),
        "cancelled": Leave.objects.filter(employee=employee, status=Leave.Status.CANCELLED).count(),
    }

    return render(request, "dashboard/employee_detail.html", {
        "employee": employee,
        "leaves_week": leaves_week,
        "leaves_month": leaves_month,
        "leaves_total": leaves_total,
        "recent_leaves": recent_leaves,
        "leave_stats": leave_stats,
        "today": today,
    })
