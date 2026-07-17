"""
Menu-driven SMS interface for leave requests.

Instead of free-form text, users navigate through a guided menu:
  1. Reply with LEAVE to start
  2. Choose leave type (SICK, VACATION, PERSONAL, MEDICAL, OTHER)
  3. Enter dates (format: MMDD-MMDD or single MMDD)
  4. Confirm or cancel
"""
import logging
from datetime import datetime, timedelta

from .models import SmsLog
from .sms import send_sms

logger = logging.getLogger(__name__)

# Session states for tracking where user is in the menu flow
class LeaveMenuState:
    IDLE = "IDLE"  # Not in menu
    AWAITING_TYPE = "AWAITING_TYPE"  # Asked for leave type
    AWAITING_DATES = "AWAITING_DATES"  # Asked for dates
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


def send_menu_prompt(phone, step=1):
    """Send the initial menu prompt to user."""
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
            "📅 ENTER DATES\n\n"
            "Format: MMDD-MMDD (range) or MMDD (single day)\n\n"
            "Examples:\n"
            "0725 = July 25 (today or later)\n"
            "0725-0730 = July 25-30\n\n"
            "Or reply CANCEL to abort"
        )
    elif step == 3:
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
    Parse leave date from user input.

    Formats accepted:
    - MMDD: Single date (assumed current or next year)
    - MMDD-MMDD: Date range
    """
    if reference_year is None:
        today = datetime.now().date()
        reference_year = today.year

    try:
        # Single date: MMDD
        if len(date_str) == 4 and "-" not in date_str:
            month = int(date_str[:2])
            day = int(date_str[2:4])
            date = datetime(reference_year, month, day).date()

            # If date is in past, assume next year
            today = datetime.now().date()
            if date < today:
                date = datetime(reference_year + 1, month, day).date()

            return date, date

        # Range: MMDD-MMDD
        elif "-" in date_str:
            parts = date_str.split("-")
            if len(parts) != 2:
                return None, None

            start_str, end_str = parts
            if len(start_str) != 4 or len(end_str) != 4:
                return None, None

            start_month = int(start_str[:2])
            start_day = int(start_str[2:4])
            start_date = datetime(reference_year, start_month, start_day).date()

            end_month = int(end_str[:2])
            end_day = int(end_str[2:4])

            # Handle year boundary (e.g., 1220-0105)
            end_year = reference_year
            if end_month < start_month:
                end_year = reference_year + 1

            end_date = datetime(end_year, end_month, end_day).date()

            # If dates in past, assume next year
            today = datetime.now().date()
            if end_date < today:
                start_date = datetime(reference_year + 1, start_month, start_day).date()
                end_date = datetime(reference_year + 1, end_month, end_day).date()

            return start_date, end_date

    except (ValueError, IndexError):
        return None, None

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
    Parse user's date input.

    Returns: (start_date, end_date, error_message)
    """
    response = response_text.strip().upper()

    if response == "CANCEL":
        return None, None, "Leave request cancelled."

    start_date, end_date = parse_date_input(response_text)

    if start_date is None:
        return None, None, (
            "Invalid date format.\n"
            "Use: MMDD or MMDD-MMDD\n"
            "Example: 0725 or 0725-0730"
        )

    today = datetime.now().date()
    if end_date < today:
        return None, None, "Leave date cannot be in the past."

    return start_date, end_date, None


def handle_reason_response(response_text):
    """Parse user's reason input."""
    response = response_text.strip().upper()

    if response == "SKIP":
        return "", None

    return response_text.strip(), None
