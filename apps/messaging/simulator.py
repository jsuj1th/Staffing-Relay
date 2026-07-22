"""
SMS Simulator — for prototype/demo use only.
Lets you test the full leave flow via browser form without a real Telnyx number.
Access at /sms-simulator/
"""
import json
import logging
from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from apps.accounts.models import Employee
from apps.messaging.views import _process_command
from apps.messaging.models import SmsLog

logger = logging.getLogger(__name__)


@require_http_methods(["GET", "POST"])
def sms_simulator(request):
    if not settings.DEBUG:
        raise Http404
    logger.debug("Simulator request: method=%s", request.method)
    employees = Employee.objects.filter(is_active=True).select_related("location").order_by("employee_type", "name")
    result = None

    if request.method == "POST":
        phone = request.POST.get("phone", "").strip()
        message = request.POST.get("message", "").strip()
        logger.info("Simulator: from=%s msg=%r", phone, message)

        employee = Employee.objects.filter(phone=phone, is_active=True).first()
        reply, leave = _process_command(phone, message, employee)

        SmsLog.objects.create(
            from_phone=phone,
            employee=employee,
            inbound_msg=message,
            outbound_msg=reply,
            leave=leave,
        )

        result = {
            "employee": employee,
            "inbound": message,
            "outbound": reply,
            "leave": leave,
            "phone": phone,
        }
        logger.info("Simulator result: status=%s", result.get("leave") and result["leave"].status or "N/A")

    return render(request, "simulator/sms_simulator.html", {
        "employees": employees,
        "result": result,
    })
