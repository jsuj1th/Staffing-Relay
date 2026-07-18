import json
import logging
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
from django.utils import timezone

from apps.accounts.models import Employee
from apps.leaves.models import Leave
from apps.leaves.ratio import evaluate_leave
from apps.messaging.models import SmsLog
from apps.messaging.parser import parse_sms, HELP_TEXT
from apps.messaging.sms import send_sms

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def telnyx_webhook(request):
    payload = request.body
    sig = request.headers.get("telnyx-signature-ed25519", "")
    timestamp = request.headers.get("telnyx-timestamp", "")

    # Verify signature when public key is configured
    if settings.TELNYX_PUBLIC_KEY:
        try:
            import telnyx
            telnyx.api_key = settings.TELNYX_API_KEY
            event = telnyx.webhooks.construct_event(
                payload.decode("utf-8"),
                sig,
                timestamp,
                settings.TELNYX_PUBLIC_KEY,
            )
        except Exception as exc:
            logger.warning("Telnyx webhook signature verification failed: %s", exc)
            return HttpResponse("Forbidden", status=403)
    else:
        # Dev mode: no signature check
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return HttpResponse("Bad Request", status=400)

    event_type = _get_event_type(event)

    if event_type != "message.received":
        return JsonResponse({"status": "ignored"})

    _handle_inbound_sms(event)
    return JsonResponse({"status": "ok"})


def _get_event_type(event):
    try:
        if isinstance(event, dict):
            return event.get("data", {}).get("event_type", "")
        return getattr(getattr(event, "data", None), "event_type", "")
    except Exception:
        return ""


def _handle_inbound_sms(event):
    try:
        if isinstance(event, dict):
            msg_payload = event["data"]["payload"]
        else:
            msg_payload = event.data.payload

        from_number = msg_payload.get("from", {}).get("phone_number") if isinstance(msg_payload, dict) else msg_payload.from_.phone_number
        text = msg_payload.get("text", "").strip() if isinstance(msg_payload, dict) else msg_payload.text.strip()
    except (KeyError, AttributeError, TypeError) as exc:
        logger.error("Could not parse inbound SMS payload: %s", exc)
        return

    logger.info("Webhook received: from=%s", from_number)

    # Look up employee (normalize phone number for lookup)
    normalized_number = _normalize_phone(from_number)
    employee = Employee.objects.filter(phone__in=[from_number, normalized_number], is_active=True).first()
    if employee is None:
        logger.info("Employee not found: phone=%s", from_number)

    reply, leave = _process_command(from_number, text, employee)

    # Menu flow handles its own sending (reply=None)
    if reply is None:
        logger.debug("Menu-driven response, skipping reply send")
        return

    # Log it
    SmsLog.objects.create(
        from_phone=from_number,
        employee=employee,
        inbound_msg=text,
        outbound_msg=reply,
        leave=leave,
    )

    send_sms(from_number, reply)


def _process_command(from_number: str, text: str, employee):
    """Route parsed command to the appropriate handler. Returns (reply_text, leave_or_None)."""
    if employee is None:
        return "Your number is not registered in our system. Please contact HR.", None

    # Check if user is in menu flow
    from apps.messaging.session import is_in_menu_flow, process_menu_response, start_leave_menu

    if is_in_menu_flow(from_number):
        # Process menu response
        result = process_menu_response(from_number, text, employee)
        if result is not None:
            return result
        # Menu sends its own prompt, return None to skip sending reply
        return None, None

    # Check if user wants to start menu flow
    if text.strip().upper() == "LEAVE":
        start_leave_menu(from_number)
        return None, None  # Menu sends prompt, skip reply

    # Parse command normally
    parsed = parse_sms(text)
    logger.debug("Parsed command: %s", parsed.command)

    if parsed.command == "help":
        return HELP_TEXT, None

    if parsed.command == "status":
        return _handle_status(employee), None

    if parsed.command == "cancel":
        return _handle_cancel(employee, parsed.cancel_date), None

    if parsed.command == "leave":
        return _handle_leave(employee, parsed)

    # Unknown command - start menu instead
    start_leave_menu(from_number)
    return None, None


def _handle_leave(employee, parsed):
    logger.info(
        "Leave request: employee=%s start=%s end=%s",
        employee.name, parsed.start_date, parsed.end_date,
    )
    today = timezone.localdate()

    if parsed.start_date < today:
        return "Leave start date cannot be in the past. Please send a future date.", None

    if parsed.end_date < parsed.start_date:
        return "End date cannot be before start date.", None

    # Check for duplicate pending/approved leave overlapping this range
    overlap = Leave.objects.filter(
        employee=employee,
        status__in=[Leave.Status.PENDING, Leave.Status.APPROVED, Leave.Status.EXTREME],
        start_date__lte=parsed.end_date,
        end_date__gte=parsed.start_date,
    ).first()
    if overlap:
        return (
            f"You already have a leave request ({overlap.start_date} to {overlap.end_date}) overlapping these dates.",
            None,
        )

    status, message, ratio_before, ratio_after = evaluate_leave(
        employee, parsed.start_date, parsed.end_date
    )

    leave = Leave.objects.create(
        employee=employee,
        start_date=parsed.start_date,
        end_date=parsed.end_date,
        reason=parsed.reason,
        status=status,
        ratio_before=ratio_before,
        ratio_after=ratio_after,
        internal_note=_build_internal_note(status, ratio_before, ratio_after),
    )
    logger.info("Leave created: id=%d status=%s", leave.id, leave.status)

    # Notify manager on extreme coverage
    if status == Leave.Status.EXTREME:
        _notify_managers_extreme(employee, leave)

    return message, leave


def _handle_status(employee):
    logger.debug("Status check: employee=%s", employee.name)
    today = timezone.localdate()
    upcoming = Leave.objects.filter(
        employee=employee,
        status__in=[Leave.Status.PENDING, Leave.Status.APPROVED, Leave.Status.EXTREME],
        end_date__gte=today,
    ).order_by("start_date")

    if not upcoming.exists():
        return "You have no upcoming leave requests."

    lines = ["Your upcoming leaves:"]
    for leave in upcoming:
        date_str = (
            str(leave.start_date)
            if leave.start_date == leave.end_date
            else f"{leave.start_date} to {leave.end_date}"
        )
        display_status = "Approved" if leave.status in (Leave.Status.APPROVED, Leave.Status.EXTREME) else "Pending"
        lines.append(f"  {date_str} ({display_status})")

    return "\n".join(lines)


def _handle_cancel(employee, cancel_date):
    logger.info("Cancel request: employee=%s date=%s", employee.name, cancel_date)
    today = timezone.localdate()

    if cancel_date is None:
        # Cancel the single upcoming leave, or ask which one
        upcoming = list(
            Leave.objects.filter(
                employee=employee,
                status__in=[Leave.Status.PENDING, Leave.Status.APPROVED, Leave.Status.EXTREME],
                start_date__gte=today,
            ).order_by("start_date")
        )
        if not upcoming:
            return "You have no upcoming leaves to cancel."
        if len(upcoming) == 1:
            leave = upcoming[0]
            leave.status = Leave.Status.CANCELLED
            leave.save()
            return f"Your leave from {leave.start_date} to {leave.end_date} has been cancelled."
        # Multiple — ask for date
        lines = ["You have multiple upcoming leaves. Reply CANCEL with the start date:"]
        for lv in upcoming:
            lines.append(f"  CANCEL {lv.start_date}")
        return "\n".join(lines)

    # Cancel by start date
    leave = Leave.objects.filter(
        employee=employee,
        start_date=cancel_date,
        status__in=[Leave.Status.PENDING, Leave.Status.APPROVED, Leave.Status.EXTREME],
    ).first()

    if not leave:
        return f"No upcoming leave found starting on {cancel_date}."

    if leave.start_date < today:
        return f"Cannot cancel a leave that has already started ({leave.start_date})."

    leave.status = Leave.Status.CANCELLED
    leave.save()
    return f"Your leave from {leave.start_date} to {leave.end_date} has been cancelled."


def _build_internal_note(status, ratio_before, ratio_after):
    if not ratio_before:
        return ""
    p_b = ratio_before.get("providers", "?")
    ma_b = ratio_before.get("mas", "?")
    p_a = ratio_after.get("providers", "?") if ratio_after else "?"
    ma_a = ratio_after.get("mas", "?") if ratio_after else "?"
    return f"Ratio before: {p_b}P:{ma_b}MA → after: {p_a}P:{ma_a}MA | Status: {status}"


def _notify_managers_extreme(employee, leave):
    """Send SMS to all active Management employees who share this location."""
    from apps.accounts.models import Employee as Emp
    location_id = employee.location_id
    managers = Emp.objects.filter(
        employee_type=Emp.Type.MANAGEMENT,
        is_active=True,
    )
    # Managers can be shared (no direct location FK), check EmployeeLocation
    from apps.locations.models import EmployeeLocation
    manager_location_ids = set(
        EmployeeLocation.objects.filter(location_id=location_id).values_list("employee_id", flat=True)
    )
    managers = managers.filter(id__in=manager_location_ids)

    msg = (
        f"[Coverage Alert] {employee.name} has a leave approved at {employee.location} "
        f"({leave.start_date} – {leave.end_date}). Current staffing is at extreme coverage."
    )
    for mgr in managers:
        if mgr.phone:
            send_sms(mgr.phone, msg)


def _normalize_phone(phone: str) -> str:
    """Normalize phone number for lookup. Handles with/without +1 prefix."""
    phone = phone.strip()
    if phone.startswith("+1"):
        return phone
    if phone.startswith("1") and len(phone) == 11:
        return "+" + phone
    if len(phone) == 10:
        return "+1" + phone
    return phone
