"""
Session state management for menu-driven SMS interactions.

Tracks user progress through leave request menu flow.
"""
import logging
from datetime import timedelta, date
from django.core.cache import cache
from django.utils import timezone

from .leave_menu import (
    LeaveMenuState,
    send_menu_prompt,
    handle_leave_type_response,
    handle_date_response,
    handle_reason_response,
    build_confirmation_message,
    LEAVE_TYPE_NAMES,
)

logger = logging.getLogger(__name__)


def get_user_session(phone):
    """Get user's current menu session state."""
    key = f"leave_menu_session:{phone}"
    return cache.get(key, {})


def set_user_session(phone, state):
    """Store user's menu session state. TTL: 24 hours."""
    key = f"leave_menu_session:{phone}"
    cache.set(key, state, timeout=86400)


def clear_user_session(phone):
    """Clear user's session (leave request completed or cancelled)."""
    key = f"leave_menu_session:{phone}"
    cache.delete(key)


def start_leave_menu(phone):
    """Initialize leave request menu for user."""
    session = {
        "state": LeaveMenuState.AWAITING_TYPE,
        "started_at": timezone.now().isoformat(),
        "leave_type": None,
        "start_date": None,
        "end_date": None,
        "is_range": False,
        "reason": None,
    }
    set_user_session(phone, session)
    send_menu_prompt(phone, step=1)
    return None  # Menu sends prompt


def process_menu_response(phone, text, employee):
    """
    Process user's response in menu flow.

    Returns: (reply_message, leave_or_None)
    """
    session = get_user_session(phone)

    if not session:
        return None  # Not in menu flow

    state = session.get("state")
    logger.debug("Menu state: phone=%s state=%s text=%s", phone, state, text)

    # Handle CANCEL at any point
    if text.strip().upper() == "CANCEL":
        clear_user_session(phone)
        return "Leave request cancelled.", None

    # Step 1: Awaiting leave type
    if state == LeaveMenuState.AWAITING_TYPE:
        leave_type, error = handle_leave_type_response(text)
        if error:
            return error, None

        session["leave_type"] = leave_type
        session["state"] = LeaveMenuState.AWAITING_START_DATE
        set_user_session(phone, session)
        send_menu_prompt(phone, step=2)
        return None, None  # Prompt sent separately

    # Step 2: Awaiting start date
    elif state == LeaveMenuState.AWAITING_START_DATE:
        start_date, _, error = handle_date_response(text)
        if error:
            if error.startswith("Leave request cancelled"):
                clear_user_session(phone)
                return error, None
            return error, None

        session["start_date"] = start_date.isoformat() if start_date else None
        session["state"] = LeaveMenuState.AWAITING_DURATION
        set_user_session(phone, session)

        # Send duration prompt with context
        send_menu_prompt(phone, step=3, context=session)
        return None, None

    # Step 3: Awaiting single or range
    elif state == LeaveMenuState.AWAITING_DURATION:
        response = text.strip().upper()

        if response == "S":
            # Single day
            start_date = date.fromisoformat(session["start_date"])
            session["end_date"] = start_date.isoformat()
            session["is_range"] = False
            session["state"] = LeaveMenuState.AWAITING_REASON
            set_user_session(phone, session)
            send_menu_prompt(phone, step=5)
            return None, None

        elif response == "R":
            # Range - ask for end date
            session["is_range"] = True
            session["state"] = LeaveMenuState.AWAITING_END_DATE
            set_user_session(phone, session)
            send_menu_prompt(phone, step=4, context=session)
            return None, None

        else:
            return "Please reply S (single day) or R (range)", None

    # Step 4: Awaiting end date (if range)
    elif state == LeaveMenuState.AWAITING_END_DATE:
        _, end_date, error = handle_date_response(text)
        if error:
            return error, None

        start_date = date.fromisoformat(session["start_date"])
        if end_date < start_date:
            return "End date cannot be before start date. Try again.", None

        session["end_date"] = end_date.isoformat()
        session["state"] = LeaveMenuState.AWAITING_REASON
        set_user_session(phone, session)
        send_menu_prompt(phone, step=5)
        return None, None

    # Step 5: Awaiting reason
    elif state == LeaveMenuState.AWAITING_REASON:
        reason, error = handle_reason_response(text)
        if error:
            return error, None

        session["reason"] = reason
        session["state"] = LeaveMenuState.AWAITING_CONFIRMATION
        set_user_session(phone, session)

        # Build confirmation
        start = date.fromisoformat(session["start_date"])
        end = date.fromisoformat(session["end_date"])
        confirmation = build_confirmation_message(
            session["leave_type"],
            start,
            end,
            reason if reason else None,
        )
        return confirmation, None

    # Step 4: Awaiting confirmation
    elif state == LeaveMenuState.AWAITING_CONFIRMATION:
        response = text.strip().upper()

        if response == "YES":
            # Submit leave request
            from apps.leaves.models import Leave
            from apps.leaves.ratio import evaluate_leave

            try:
                start_date = date.fromisoformat(session["start_date"])
                end_date = date.fromisoformat(session["end_date"])

                # Evaluate leave
                status, message, ratio_before, ratio_after = evaluate_leave(
                    employee, start_date, end_date
                )

                # Create leave
                leave = Leave.objects.create(
                    employee=employee,
                    start_date=start_date,
                    end_date=end_date,
                    reason=session["reason"],
                    status=status,
                    ratio_before=ratio_before,
                    ratio_after=ratio_after,
                    internal_note=f"[MENU] {session['leave_type']} - {message}",
                )

                clear_user_session(phone)
                logger.info(
                    "Leave created via menu: id=%d employee=%s status=%s",
                    leave.id,
                    employee.name,
                    status,
                )

                return message, leave

            except Exception as e:
                logger.error("Error creating leave from menu: %s", e)
                clear_user_session(phone)
                return "Error submitting leave. Please contact support.", None

        elif response == "NO":
            clear_user_session(phone)
            return "Leave request cancelled.", None

        else:
            return "Please reply YES to confirm or NO to cancel.", None

    return None, None


def is_in_menu_flow(phone):
    """Check if user is currently in a menu flow."""
    session = get_user_session(phone)
    return bool(session and session.get("state") != LeaveMenuState.IDLE)
