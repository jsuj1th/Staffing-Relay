import json
import logging
from datetime import date, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Q
from django.conf import settings

from apps.accounts.models import Employee
from apps.locations.models import Location, EmployeeLocation
from apps.leaves.models import Leave
from apps.messaging.models import SmsLog
from apps.messaging.sms import send_sms
from apps.leaves.ratio import get_active_counts
from apps.shifts.models import Shift
from apps.dashboard.forms import ShiftForm

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
    return render(request, "registration/login.html", {"debug": settings.DEBUG})


def debug_login(request):
    """DEBUG MODE ONLY: Skip login as admin user for development."""
    if not settings.DEBUG:
        return redirect("dashboard:login")

    admin_user = User.objects.filter(username='admin').first()
    if admin_user:
        login(request, admin_user)
        return redirect(request.GET.get("next", "dashboard:overview"))

    messages.error(request, "Admin user not found.")
    return redirect("dashboard:login")


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
    qs = Employee.objects.select_related("location").prefetch_related(
        "employee_locations__location"
    ).all()
    type_filter = request.GET.get("type", "")
    location_filter = request.GET.get("location", "")
    if type_filter:
        qs = qs.filter(employee_type=type_filter)
    if location_filter:
        # Match direct-location employees AND shared ones linked via EmployeeLocation.
        qs = qs.filter(
            Q(location_id=location_filter)
            | Q(employee_locations__location_id=location_filter)
        ).distinct()

    today = timezone.localtime()
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
        phone = Employee.normalize_phone(request.POST.get("phone", "").strip())
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
        phone = Employee.normalize_phone(request.POST.get("phone", emp.phone).strip())
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
    qs = Leave.objects.select_related("employee", "employee__location").prefetch_related(
        "employee__employee_locations__location"
    )
    status_filter = request.GET.get("status", "")
    location_filter = request.GET.get("location", "")
    period_filter = request.GET.get("period", "")

    if status_filter:
        qs = qs.filter(status=status_filter)
    if location_filter:
        # Include shared employees linked via EmployeeLocation, not just direct FK.
        qs = qs.filter(
            Q(employee__location_id=location_filter)
            | Q(employee__employee_locations__location_id=location_filter)
        ).distinct()

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
    phone = request.GET.get("phone")

    # Thread view: the full conversation with one number, oldest-first (chat order).
    if phone:
        thread = (
            SmsLog.objects.filter(from_phone=phone)
            .select_related("employee", "leave")
            .order_by("created_at")
        )
        employee = next((log.employee for log in thread if log.employee), None)
        return render(request, "dashboard/sms_thread.html", {
            "phone": phone,
            "employee": employee,
            "logs": thread,
        })

    # Conversation list: one row per number, most recent activity first.
    logs = SmsLog.objects.select_related("employee").order_by("-created_at")[:1000]
    conversations = {}
    for log in logs:
        convo = conversations.get(log.from_phone)
        if convo is None:
            # First (newest) row for this number sets the preview + timestamp.
            conversations[log.from_phone] = {
                "phone": log.from_phone,
                "employee": log.employee,
                "last_time": log.created_at,
                "preview": log.outbound_msg or log.inbound_msg or "",
                "count": 1,
            }
        else:
            convo["count"] += 1
            if convo["employee"] is None and log.employee:
                convo["employee"] = log.employee
    return render(request, "dashboard/sms_logs.html", {
        "conversations": list(conversations.values()),
    })


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

    from apps.messaging.models import NotificationSetting
    return render(request, "dashboard/shifts.html", {
        "locations": locations,
        "selected_location": selected_location,
        "selected_date": selected_date,
        "rows": rows,
        "today": today,
        "shift_sms_enabled": NotificationSetting.load().shift_assignment_enabled,
    })


@login_required
def combined_schedule(request):
    """All locations at once for one week (Mon–Fri): locations as rows, days as
    columns, everyone scheduled in each cell, color-coded by confirmation."""
    today = timezone.localdate()
    try:
        week_date = date.fromisoformat(request.GET["date"]) if request.GET.get("date") else today
    except (ValueError, KeyError):
        week_date = today
    week_start = week_date - timedelta(days=week_date.weekday())  # Monday
    days = [week_start + timedelta(days=i) for i in range(5)]     # Mon–Fri

    shifts = (
        Shift.objects.filter(date__gte=days[0], date__lte=days[-1], employee__is_active=True)
        .select_related("employee", "employee__location")
        .prefetch_related("employee__employee_locations__location")
        .order_by("employee__employee_type", "employee__name", "start_time")
    )

    locations = list(Location.objects.all().order_by("name"))
    grid = {loc.id: {d: [] for d in days} for loc in locations}
    unassigned = {d: [] for d in days}
    for s in shifts:
        loc = s.employee.location
        if loc is None:  # shared employee — use their primary/first linked location
            el = s.employee.employee_locations.first()
            loc = el.location if el else None
        bucket = grid[loc.id] if (loc and loc.id in grid) else unassigned
        bucket[s.date].append(s)

    rows = [{"location": loc, "cells": [grid[loc.id][d] for d in days]} for loc in locations]
    if any(unassigned[d] for d in days):
        rows.append({"location": None, "cells": [unassigned[d] for d in days]})

    return render(request, "dashboard/combined_schedule.html", {
        "week_start": week_start,
        "prev_week": (week_start - timedelta(days=7)).isoformat(),
        "next_week": (week_start + timedelta(days=7)).isoformat(),
        "this_week": (today - timedelta(days=today.weekday())).isoformat(),
        "days": days,
        "rows": rows,
        "today": today,
    })


@login_required
def shift_toggle_status(request, pk):
    """Toggle a shift's confirmed (blue) or needs_attention (yellow) flag."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    shift = get_object_or_404(Shift, pk=pk)
    action = request.POST.get("action")
    if action == "confirm":
        shift.confirmed = not shift.confirmed
        shift.save(update_fields=["confirmed"])
    elif action == "flag":
        shift.needs_attention = not shift.needs_attention
        shift.save(update_fields=["needs_attention"])
    return redirect(request.META.get("HTTP_REFERER") or "dashboard:combined_schedule")


@login_required
def toggle_shift_notifications(request):
    """Flip the global shift-assignment SMS switch."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    from apps.messaging.models import NotificationSetting
    setting = NotificationSetting.load()
    setting.shift_assignment_enabled = not setting.shift_assignment_enabled
    setting.save(update_fields=["shift_assignment_enabled"])
    state = "ON" if setting.shift_assignment_enabled else "OFF"
    logger.info("Shift-assignment SMS toggled %s by %s", state, request.user)
    messages.success(request, f"Shift-assignment notifications turned {state}.")
    return redirect(request.META.get("HTTP_REFERER") or "dashboard:shifts")


@login_required
def shift_remind(request, pk):
    """Manually text an employee a reminder of a specific shift."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    shift = get_object_or_404(Shift, pk=pk)
    from apps.messaging.notifications import notify_shift_reminder
    if notify_shift_reminder(shift):
        messages.success(request, f"Reminder sent to {shift.employee.name}.")
    else:
        messages.error(request, f"Could not send reminder to {shift.employee.name} (check the number / SMS logs).")
    return redirect(request.META.get("HTTP_REFERER") or "dashboard:shifts")


@login_required
def weekly_planner(request):
    """New drag-drop weekly schedule planner."""
    today = timezone.localdate()
    location_id = request.GET.get("location", "")
    date_str = request.GET.get("date", "")

    # Get week start date
    try:
        week_date = date.fromisoformat(date_str) if date_str else today
    except ValueError:
        week_date = today

    # Get Monday of this week
    week_start = week_date - timedelta(days=week_date.weekday())
    week_end = week_start + timedelta(days=6)

    locations = Location.objects.all()
    selected_location = None
    available_employees = []

    if location_id:
        try:
            selected_location = get_object_or_404(Location, pk=int(location_id))
            available_employees = Employee.objects.filter(
                location=selected_location,
                employee_type__in=[Employee.Type.PROVIDER, Employee.Type.MEDICAL_ASSISTANT],
                is_active=True,
            ).order_by("name")
        except (ValueError, Location.DoesNotExist):
            pass

    # Get all shifts for this week
    shifts_by_day = {}
    if selected_location:
        shifts = Shift.objects.filter(
            employee__location=selected_location,
            date__gte=week_start,
            date__lte=week_end,
        ).select_related("employee").order_by("date", "start_time")

        for shift in shifts:
            day_key = shift.date.isoformat()
            if day_key not in shifts_by_day:
                shifts_by_day[day_key] = []
            shifts_by_day[day_key].append(shift)

    # Per-day leave map: which employees are on leave on each specific date
    # (a 1-day absence only blocks that day, not the whole week)
    leave_names_by_date = {}   # iso date -> [names] for display in the day cell
    leave_ids_by_date = {}     # iso date -> [employee_ids] for JS drop-blocking
    if selected_location:
        leaves = Leave.objects.filter(
            employee__location=selected_location,
            start_date__lte=week_end,
            end_date__gte=week_start,
            status__in=[Leave.Status.APPROVED, Leave.Status.EXTREME],
        ).select_related("employee")
        for lv in leaves:
            d = max(lv.start_date, week_start)
            last = min(lv.end_date, week_end)
            while d <= last:
                key = d.isoformat()
                leave_names_by_date.setdefault(key, []).append(lv.employee.name)
                leave_ids_by_date.setdefault(key, []).append(lv.employee_id)
                d += timedelta(days=1)

    # Build week days
    days = []
    for i in range(7):
        day = week_start + timedelta(days=i)
        days.append({
            "date": day,
            "day_name": day.strftime("%A"),
            "shifts": shifts_by_day.get(day.isoformat(), []),
            "on_leave": leave_names_by_date.get(day.isoformat(), []),
        })

    return render(request, "dashboard/weekly_planner.html", {
        "locations": locations,
        "selected_location": selected_location,
        "week_start": week_start,
        "week_end": week_end,
        "days": days,
        "available_employees": available_employees,
        "leave_ids_by_date": leave_ids_by_date,
        "today": today,
    })


@login_required
def api_add_shift_to_planner(request):
    """API endpoint: Add shift from weekly planner (drag-drop)."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        employee_id = data.get("employee_id")
        date_str = data.get("date")

        employee = get_object_or_404(Employee, pk=employee_id)
        shift_date = date.fromisoformat(date_str)

        # Block scheduling on a day the employee has approved leave
        if Leave.objects.filter(
            employee=employee,
            start_date__lte=shift_date,
            end_date__gte=shift_date,
            status__in=[Leave.Status.APPROVED, Leave.Status.EXTREME],
        ).exists():
            return JsonResponse(
                {"error": f"{employee.name} is on leave that day."}, status=400
            )

        # Times come as "HH:MM" strings; lexical compare == chronological.
        start_time = data.get("start_time") or "08:00"
        end_time = data.get("end_time") or "17:00"
        if end_time <= start_time:
            return JsonResponse({"error": "End time must be after start time."}, status=400)

        shift = Shift.objects.create(
            employee=employee,
            date=shift_date,
            start_time=start_time,
            end_time=end_time,
            created_by=request.user,
        )

        logger.info(f"Shift created via planner: {employee.name} - {shift_date}")

        # Single manual assignment: send SMS now (bulk copy-week stays batched)
        from apps.messaging.notifications import notify_shift_assigned
        notify_shift_assigned(shift, send_immediately=True)

        return JsonResponse({
            "success": True,
            "shift_id": shift.id,
            "message": f"Shift added for {employee.name}",
        })
    except Exception as e:
        logger.error(f"Error adding shift: {e}")
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def api_delete_shift_from_planner(request, shift_id):
    """API endpoint: Delete shift from planner."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        shift = get_object_or_404(Shift, pk=shift_id)
        emp_name = shift.employee.name
        from apps.messaging.notifications import notify_shift_cancelled
        notify_shift_cancelled(shift)  # before delete: needs shift data
        shift.delete()
        logger.info(f"Shift deleted via planner: {emp_name}")
        return JsonResponse({"success": True, "message": f"Shift removed for {emp_name}"})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def api_copy_week(request):
    """API endpoint: Copy shifts from one week to next week."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        location_id = data.get("location_id")
        from_date_str = data.get("from_date")
        to_date_str = data.get("to_date")

        location = get_object_or_404(Location, pk=location_id)
        from_date = date.fromisoformat(from_date_str)
        to_date = date.fromisoformat(to_date_str)

        # Get Monday of from_date week
        from_week = from_date - timedelta(days=from_date.weekday())
        from_week_end = from_week + timedelta(days=6)

        # Get shifts from source week
        shifts_to_copy = Shift.objects.filter(
            employee__location=location,
            date__gte=from_week,
            date__lte=from_week_end,
        )

        # Calculate day offset
        to_week = to_date - timedelta(days=to_date.weekday())
        day_offset = (to_week - from_week).days

        # Create new shifts
        from apps.messaging.notifications import notify_shift_assigned
        created_count = 0
        for shift in shifts_to_copy:
            new_date = shift.date + timedelta(days=day_offset)

            # Check if shift already exists
            if not Shift.objects.filter(
                employee=shift.employee,
                date=new_date,
                start_time=shift.start_time,
                end_time=shift.end_time,
            ).exists():
                new_shift = Shift.objects.create(
                    employee=shift.employee,
                    date=new_date,
                    start_time=shift.start_time,
                    end_time=shift.end_time,
                    created_by=request.user,
                )
                # Queue batched SMS (won't spam — batching combines them)
                notify_shift_assigned(new_shift, send_immediately=False)
                created_count += 1

        logger.info(f"Week copied: {created_count} shifts created")
        return JsonResponse({
            "success": True,
            "created": created_count,
            "message": f"{created_count} shifts copied to next week",
        })
    except Exception as e:
        logger.error(f"Error copying week: {e}")
        return JsonResponse({"error": str(e)}, status=400)


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
        form = ShiftForm(request.POST)
        logger.debug(f"shift_create POST: form valid={form.is_valid()}, errors={form.errors if not form.is_valid() else 'none'}")
        if form.is_valid():
            shift = form.save(commit=False)
            shift.created_by = request.user

            repeat_weeks = int(request.POST.get("repeat_weeks", 0) or 0)
            repeat_weeks = min(max(repeat_weeks, 0), 52)

            shift.save()

            # Create repeated shifts
            for week in range(1, repeat_weeks + 1):
                Shift.objects.create(
                    employee=shift.employee, date=shift.date + timedelta(weeks=week),
                    start_time=shift.start_time, end_time=shift.end_time,
                    created_by=request.user,
                )

            logger.info("Shift created: employee=%s date=%s repeat_weeks=%d", shift.employee.name, shift.date, repeat_weeks)

            # Single shift: SMS now. Repeated shifts: batch into one digest.
            from apps.messaging.notifications import notify_shift_assigned
            notify_shift_assigned(shift, send_immediately=not repeat_weeks)

            if repeat_weeks:
                for week in range(1, repeat_weeks + 1):
                    repeated_shift = Shift.objects.get(
                        employee=shift.employee,
                        date=shift.date + timedelta(weeks=week),
                    )
                    notify_shift_assigned(repeated_shift, send_immediately=False)

            sms_note = " SMS sent." if not repeat_weeks else " SMS notifications queued."
            messages.success(request, f"Shift added for {shift.employee.name}" + (f" (repeated {repeat_weeks} weeks)" if repeat_weeks else "") + "." + sms_note)
            return redirect(f"/dashboard/shifts/?location={shift.employee.location_id}&date={shift.date}")
    else:
        form = ShiftForm()

    return render(request, "dashboard/shift_form.html", {
        "form": form,
        "locations": locations, "employees": employees, "action": "Add",
        "preselect_location_id": preselect_location_id,
        "preselect_date": preselect_date,
    })


@login_required
def shift_edit(request, pk):
    shift = get_object_or_404(Shift, pk=pk)

    if request.method == "POST":
        before = (shift.date, shift.start_time, shift.end_time)
        try:
            shift.date = date.fromisoformat(request.POST.get("date", str(shift.date)))
        except ValueError:
            messages.error(request, "Invalid date.")
            return render(request, "dashboard/shift_form.html", {
                "shift": shift, "action": "Edit", "form": ShiftForm(request.POST),
                "locations": Location.objects.all(),
            })
        shift.start_time = request.POST.get("start_time", shift.start_time)
        shift.end_time = request.POST.get("end_time", shift.end_time)
        shift.save()
        shift.refresh_from_db()  # POST gives strings; reload so times compare as time objects
        logger.info("Shift updated: id=%d employee=%s", shift.id, shift.employee.name)

        # Notify only if date/time actually changed (skip no-op saves)
        if before != (shift.date, shift.start_time, shift.end_time):
            from apps.messaging.notifications import notify_shift_updated
            notify_shift_updated(shift)

        messages.success(request, "Shift updated.")
        return redirect(f"/dashboard/shifts/?location={shift.employee.location_id}&date={shift.date}")

    # Prefill time dropdowns with the shift's current times (ChoiceField wants "HH:MM").
    form = ShiftForm(initial={
        "start_time": shift.start_time.strftime("%H:%M"),
        "end_time": shift.end_time.strftime("%H:%M"),
    })
    return render(request, "dashboard/shift_form.html", {
        "shift": shift, "action": "Edit", "form": form,
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
    from apps.messaging.notifications import notify_shift_cancelled
    notify_shift_cancelled(shift)  # before delete: needs shift data
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


# Admin leave management views


@login_required
def leave_approve(request, pk):
    """Admin approves a leave request."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    leave = get_object_or_404(Leave, pk=pk)
    old_status = leave.status
    leave.status = Leave.Status.APPROVED
    leave.approved_by = request.user
    leave.save(update_fields=["status", "approved_by", "updated_at"])

    logger.info("Leave approved: id=%d by=%s", leave.id, request.user)

    # Notify employee via SMS
    from apps.messaging.notifications import notify_leave_approved

    notify_leave_approved(leave, send_immediately=True)

    messages.success(request, f"Leave approved and employee notified via SMS.")
    return redirect("dashboard:leaves")


@login_required
def leave_reject(request, pk):
    """Admin rejects a leave request with optional reason."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    leave = get_object_or_404(Leave, pk=pk)
    reason = request.POST.get("reason", "").strip()

    old_status = leave.status
    leave.status = Leave.Status.REJECTED
    if reason:
        leave.internal_note = reason
    leave.approved_by = request.user
    leave.save(update_fields=["status", "internal_note", "approved_by", "updated_at"])

    logger.info("Leave rejected: id=%d by=%s", leave.id, request.user)

    # Notify employee via SMS
    from apps.messaging.notifications import notify_leave_rejected

    notify_leave_rejected(leave, send_immediately=True)

    messages.success(request, f"Leave rejected and employee notified via SMS.")
    return redirect("dashboard:leaves")


@login_required
def leave_cancel(request, pk):
    """Admin cancels an approved or pending leave."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    leave = get_object_or_404(Leave, pk=pk)
    old_status = leave.status
    leave.status = Leave.Status.CANCELLED
    leave.approved_by = request.user
    leave.save(update_fields=["status", "approved_by", "updated_at"])

    logger.info("Leave cancelled: id=%d by=%s", leave.id, request.user)

    # Notify employee via SMS
    from apps.messaging.notifications import notify_leave_cancelled

    notify_leave_cancelled(leave, send_immediately=True)

    messages.success(request, f"Leave cancelled and employee notified via SMS.")
    return redirect("dashboard:leaves")


@login_required
def leave_edit(request, pk):
    """Admin edits a leave record."""
    from .forms import LeaveForm

    leave = get_object_or_404(Leave, pk=pk)
    old_status = leave.status

    if request.method == "POST":
        form = LeaveForm(request.POST, instance=leave)
        if form.is_valid():
            leave = form.save(commit=False)
            leave.approved_by = request.user
            leave.save()

            logger.info("Leave edited: id=%d by=%s", leave.id, request.user)

            # Send notification only if status changed
            if old_status != leave.status:
                from apps.messaging.notifications import (
                    notify_leave_approved,
                    notify_leave_rejected,
                )

                if leave.status == Leave.Status.APPROVED:
                    notify_leave_approved(leave, send_immediately=True)
                elif leave.status == Leave.Status.REJECTED:
                    notify_leave_rejected(leave, send_immediately=True)
                messages.success(
                    request,
                    f"Leave updated and employee notified via SMS.",
                )
            else:
                messages.success(request, "Leave updated successfully.")

            return redirect("dashboard:leaves")
    else:
        form = LeaveForm(instance=leave)

    return render(request, "dashboard/leave_form.html", {
        "form": form,
        "leave": leave,
        "action": "Edit",
    })
