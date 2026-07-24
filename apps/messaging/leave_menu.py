"""
Menu-driven SMS interface for leave requests.

Instead of free-form text, users navigate through a guided menu:
  1. Reply with LEAVE to start
  2. Choose leave type (SICK, VACATION, PERSONAL, MEDICAL, OTHER)
  3. Enter dates (format: MMDD-MMDD or single MMDD)
  4. Confirm or cancel
"""
import logging
from datetime import datetime, timedelta, date

from .models import SmsLog
from .sms import send_sms

logger = logging.getLogger(__name__)

# Session states for tracking where user is in the menu flow
class LeaveMenuState:
    IDLE = "IDLE"  # Not in menu
    AWAITING_MAIN_CHOICE = "AWAITING_MAIN_CHOICE"  # Asked for main menu option
    AWAITING_TYPE = "AWAITING_TYPE"  # Asked for leave type
    AWAITING_START_DATE = "AWAITING_START_DATE"  # Asked for start date
    AWAITING_DURATION = "AWAITING_DURATION"  # Asked: single day or range?
    AWAITING_END_DATE = "AWAITING_END_DATE"  # Asked for end date (if range)
    AWAITING_REASON = "AWAITING_REASON"  # Asked for reason
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"  # Ready to submit


LEAVE_TYPES = {
    "1": "SICK",
    "2": "VACATION",
    "3": "PERSONAL",
    "4": "MEDICAL",
    "5": "OTHER",
}

LEAVE_TYPE_NAMES = {
    "SICK": "Sick Leave",
    "VACATION": "Vacation",
    "PERSONAL": "Personal Leave",
    "MEDICAL": "Medical Leave",
    "OTHER": "Other",
}


def send_main_menu(phone):
    """Send main menu to user."""
    message = (
        "📋 RELAY MENU\n\n"
        "1 = Request Leave\n"
        "2 = Check Leave Status\n"
        "3 = Cancel Leave\n"
        "4 = Help\n\n"
        "Reply with: 1, 2, 3, or 4"
    )
    send_sms(phone, message)
    logger.info("Main menu sent: phone=%s", phone)


def send_menu_prompt(phone, step=1, context=None):
    """Send menu prompt to user."""
    if step == 1:
        message = (
            "📋 RELAY LEAVE REQUEST\n\n"
            "Reply with leave type:\n"
            "1 = Sick Leave\n"
            "2 = Vacation\n"
            "3 = Personal\n"
            "4 = Medical\n"
            "5 = Other\n\n"
            "Example: Reply '2' for vacation"
        )
    elif step == 2:
        message = (
            "📅 START DATE\n\n"
            "Format: MMDD (month + day)\n\n"
            "Examples:\n"
            "0725 = July 25, 2026\n"
            "0105 = January 5, 2027\n\n"
            "Or reply EXIT to abort"
        )
    elif step == 3:
        if context and "start_date" in context:
            start_date_obj = (
                context["start_date"]
                if isinstance(context["start_date"], datetime)
                else datetime.fromisoformat(context["start_date"]).date()
            )
            start_str = start_date_obj.strftime("%a, %b %d")
            message = (
                f"📅 DURATION\n\n"
                f"Start: {start_str}\n\n"
                f"Reply:\n"
                f"S = Single day ({start_str})\n"
                f"R = Range (then enter end date)\n\n"
                f"Example: Reply 'S' or 'R'"
            )
        else:
            message = "Reply: S = Single day, R = Range"
    elif step == 4:
        if context and "start_date" in context:
            start_date_obj = (
                context["start_date"]
                if isinstance(context["start_date"], datetime)
                else datetime.fromisoformat(context["start_date"]).date()
            )
            start_str = start_date_obj.strftime("%a, %b %d")
            message = (
                f"📅 END DATE\n\n"
                f"Start: {start_str}\n"
                f"End: ?\n\n"
                f"Format: MMDD (same as start date entry)\n\n"
                f"Example: 0730 = July 30, 2026"
            )
        else:
            message = "📅 END DATE\n\nFormat: MMDD"
    elif step == 5:
        message = (
            "📝 REASON (optional)\n\n"
            "Brief reason for leave:\n"
            "(Or reply SKIP if not needed)"
        )
    else:
        message = ""

    send_sms(phone, message)
    logger.info("Menu prompt sent: phone=%s step=%d", phone, step)


def parse_date_input(date_str, reference_year=None):
    """
    Parse a single leave date from user input.

    Format: MMDD (month + day)
    Returns: (parsed_date, None)

    Example:
    - "0725" → July 25, 2026 (if in future)
    - "0105" → January 5, 2027 (next year if today is in 2026)
    """
    if reference_year is None:
        today = datetime.now().date()
        reference_year = today.year

    try:
        date_str = date_str.strip()

        if len(date_str) != 4:
            return None, None

        month = int(date_str[:2])
        day = int(date_str[2:4])

        if month < 1 or month > 12 or day < 1 or day > 31:
            return None, None

        # Try current year first
        try:
            parsed_date = datetime(reference_year, month, day).date()
        except ValueError:
            # Invalid date (e.g., Feb 30)
            return None, None

        today = datetime.now().date()

        # If date is in past, assume next year
        if parsed_date < today:
            try:
                parsed_date = datetime(reference_year + 1, month, day).date()
            except ValueError:
                return None, None

        return parsed_date, None

    except (ValueError, IndexError):
        return None, None


def build_confirmation_message(leave_type, start_date, end_date, reason=None):
    """Build a formatted confirmation message."""
    duration = (end_date - start_date).days + 1
    date_str = (
        start_date.strftime("%b %d")
        if start_date == end_date
        else f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d')}"
    )

    message = (
        f"📋 LEAVE REQUEST SUMMARY\n\n"
        f"Type: {LEAVE_TYPE_NAMES.get(leave_type, leave_type)}\n"
        f"Dates: {date_str}\n"
        f"Duration: {duration} day{'s' if duration > 1 else ''}\n"
    )

    if reason:
        message += f"Reason: {reason}\n"

    message += (
        "\n✅ Reply YES to submit\n"
        "❌ Reply NO to cancel"
    )

    return message


# Menu flow responses

def handle_leave_type_response(response_text):
    """
    Parse user's leave type selection.

    Returns: (leave_type, error_message)
    """
    response = response_text.strip().upper()

    if response in LEAVE_TYPES:
        return LEAVE_TYPES[response], None

    return None, (
        "Invalid selection. Reply with:\n"
        "1=Sick, 2=Vacation, 3=Personal, 4=Medical, 5=Other"
    )


def handle_date_response(response_text):
    """
    Parse user's date input (single date only).

    Returns: (parsed_date, None, error_message)
    """
    response = response_text.strip().upper()

    if response == "EXIT":
        return None, None, "Leave request cancelled."

    parsed_date, _ = parse_date_input(response_text)

    if parsed_date is None:
        return None, None, (
            "Invalid date format.\n"
            "Use: MMDD (month + day)\n"
            "Example: 0725 = July 25, 2026"
        )

    today = datetime.now().date()
    if parsed_date < today:
        return None, None, "Date cannot be in the past. Try again."

    return parsed_date, None, None


def handle_reason_response(response_text):
    """Parse user's reason input."""
    response = response_text.strip().upper()

    if response == "SKIP":
        return "", None

    return response_text.strip(), None


def build_status_message(employee):
    """Build leave status message for employee."""
    from apps.leaves.models import Leave
    from django.utils import timezone

    today = timezone.localdate()

    # Get upcoming approved/pending leaves
    upcoming = Leave.objects.filter(
        employee=employee,
        status__in=[Leave.Status.PENDING, Leave.Status.APPROVED, Leave.Status.EXTREME],
        end_date__gte=today,
    ).order_by("start_date")

    # Get recent rejections (past 30 days)
    cutoff_date = today - timedelta(days=30)
    recent_rejections = Leave.objects.filter(
        employee=employee,
        status=Leave.Status.REJECTED,
        created_at__gte=cutoff_date,
    ).order_by("-created_at")

    lines = ["📊 YOUR LEAVE STATUS\n"]

    if upcoming.exists():
        lines.append(f"Upcoming ({upcoming.count()}):")
        for leave in upcoming[:5]:  # Show up to 5 upcoming
            date_str = (
                str(leave.start_date)
                if leave.start_date == leave.end_date
                else f"{leave.start_date}–{leave.end_date}"
            )
            status_icon = "✅" if leave.status in (Leave.Status.APPROVED, Leave.Status.EXTREME) else "⏳"
            display_status = "Approved" if leave.status in (Leave.Status.APPROVED, Leave.Status.EXTREME) else "Pending"
            lines.append(f"{status_icon} {date_str} ({display_status})")
        if upcoming.count() > 5:
            lines.append(f"... and {upcoming.count() - 5} more")
    else:
        lines.append("No upcoming leaves.")

    if recent_rejections.exists():
        lines.append(f"\nRecent Rejections ({recent_rejections.count()}):")
        for leave in recent_rejections[:3]:  # Show up to 3 rejections
            date_str = (
                str(leave.start_date)
                if leave.start_date == leave.end_date
                else f"{leave.start_date}–{leave.end_date}"
            )
            lines.append(f"❌ {date_str}")
        if recent_rejections.count() > 3:
            lines.append(f"... and {recent_rejections.count() - 3} more")

    return "\n".join(lines)
