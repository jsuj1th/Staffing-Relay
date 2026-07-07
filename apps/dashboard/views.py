import json
import logging
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
    locations = Location.objects.all()
    return render(request, "dashboard/employees.html", {
        "employees": qs,
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
def leave_list(request):
    qs = Leave.objects.select_related("employee", "employee__location")
    status_filter = request.GET.get("status", "")
    location_filter = request.GET.get("location", "")
    if status_filter:
        qs = qs.filter(status=status_filter)
    if location_filter:
        qs = qs.filter(employee__location_id=location_filter)
    locations = Location.objects.all()
    return render(request, "dashboard/leaves.html", {
        "leaves": qs.order_by("-created_at")[:200],
        "locations": locations,
        "status_filter": status_filter,
        "location_filter": location_filter,
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
        reply = "Your leave request has been approved by your manager."
    else:
        leave.status = Leave.Status.REJECTED
        reply = "Your leave request has been reviewed and cannot be approved at this time. Please contact your manager."

    if note:
        leave.internal_note = note
    leave.approved_by = request.user
    leave.save()
    logger.info("Leave action: id=%d action=%s by=%s", leave.id, action, request.user)

    # Notify employee via SMS
    send_sms(leave.employee.phone, reply)
    SmsLog.objects.create(
        from_phone=leave.employee.phone,
        employee=leave.employee,
        inbound_msg=f"[Dashboard] Manager changed status from {old_status} to {leave.status}",
        outbound_msg=reply,
        leave=leave,
    )

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
