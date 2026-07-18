"""
SMS Notification system with batching support.

Features:
- Queue notifications for batching (default: 1 hour batch window)
- Combine multiple shift assignments into one SMS
- Immediate send option for urgent notifications
- Track all outgoing notifications
- DEBUG mode: Force immediate sending for testing
"""
import logging
from datetime import timedelta
from django.utils import timezone
from django.conf import settings

from .models import NotificationQueue, SmsLog
from .sms import send_sms

logger = logging.getLogger(__name__)

# DEBUG mode: Set to True to send notifications immediately (for testing)
DEBUG = getattr(settings, 'SMS_DEBUG', False)


def queue_notification(
    employee,
    notification_type,
    message_body,
    related_object_id=None,
    send_immediately=False,
    batch_window_minutes=60,
):
    """
    Queue an SMS notification for the employee.

    Args:
        employee: Employee to notify
        notification_type: Type of notification (from NotificationQueue.NotificationType)
        message_body: Message text to send
        related_object_id: ID of related Shift or Leave (optional)
        send_immediately: If True, send right away (default: batch)
        batch_window_minutes: Minutes to wait before sending batch (default: 60)

    Returns:
        NotificationQueue object
    """
    # DEBUG mode: Force immediate sending
    if DEBUG:
        send_immediately = True
        logger.info("DEBUG MODE: Forcing immediate send for notification (employee=%s)", employee.id)

    scheduled_send_at = timezone.now() if send_immediately else (
        timezone.now() + timedelta(minutes=batch_window_minutes)
    )

    notification = NotificationQueue.objects.create(
        employee=employee,
        notification_type=notification_type,
        message_body=message_body,
        related_object_id=related_object_id,
        scheduled_send_at=scheduled_send_at,
    )

    if DEBUG:
        logger.debug(f"Notification queued: type={notification_type}, employee={employee.name}, message={message_body}")
        pending_count = NotificationQueue.objects.filter(
            employee=employee,
            is_sent=False,
        ).count()
        logger.debug(f"Pending notifications: {pending_count} for employee={employee.name}")

    logger.info(
        "Notification queued: employee=%s type=%s send_at=%s",
        employee.name,
        notification_type,
        scheduled_send_at,
    )

    if send_immediately:
        send_notification_batch(employee)

    return notification


def send_notification_batch(employee):
    """
    Send all pending notifications for an employee as a single batched SMS.

    Combines multiple notifications into one message to avoid SMS spam.
    """
    pending = NotificationQueue.objects.filter(
        employee=employee,
        is_sent=False,
        scheduled_send_at__lte=timezone.now(),
    ).order_by("created_at")

    if not pending.exists():
        logger.debug("No pending notifications for %s", employee.name)
        return

    # Group by type for better formatting
    by_type = {}
    for notif in pending:
        if notif.notification_type not in by_type:
            by_type[notif.notification_type] = []
        by_type[notif.notification_type].append(notif)

    # Build combined message
    lines = ["📋 RELAY UPDATES:\n"]

    if NotificationQueue.NotificationType.SHIFT_ASSIGNED in by_type:
        shifts = by_type[NotificationQueue.NotificationType.SHIFT_ASSIGNED]
        lines.append(f"🕐 SHIFTS ASSIGNED ({len(shifts)}):")
        for shift_notif in shifts[:3]:  # Limit to 3 in SMS
            lines.append(f"  • {shift_notif.message_body}")
        if len(shifts) > 3:
            lines.append(f"  ... and {len(shifts) - 3} more")
        lines.append("")

    if NotificationQueue.NotificationType.LEAVE_APPROVED in by_type:
        leaves = by_type[NotificationQueue.NotificationType.LEAVE_APPROVED]
        lines.append(f"✅ LEAVE APPROVED ({len(leaves)}):")
        for leave_notif in leaves:
            lines.append(f"  {leave_notif.message_body}")
        lines.append("")

    if NotificationQueue.NotificationType.LEAVE_REJECTED in by_type:
        leaves = by_type[NotificationQueue.NotificationType.LEAVE_REJECTED]
        lines.append(f"❌ LEAVE REJECTED ({len(leaves)}):")
        for leave_notif in leaves:
            lines.append(f"  {leave_notif.message_body}")
        lines.append("")

    combined_message = "\n".join(lines).strip()

    # Send SMS
    try:
        if DEBUG:
            logger.debug(f"Sending batch: {len(pending)} notifications to {employee.name}")
        send_sms(employee.phone, combined_message)
        if DEBUG:
            logger.debug(f"Batch sent successfully: employee={employee.name}, count={len(pending)}")
        logger.info(
            "Notification batch sent: employee=%s count=%d",
            employee.name,
            len(pending),
        )

        # Mark as sent
        now = timezone.now()
        for notif in pending:
            notif.is_sent = True
            notif.sent_at = now
            notif.save()

        # Log in SmsLog
        SmsLog.objects.create(
            from_phone=employee.phone,
            employee=employee,
            inbound_msg="[Batch notification]",
            outbound_msg=combined_message,
        )

    except Exception as e:
        logger.error("Failed to send notification batch: %s", e)
        raise


def send_all_pending_notifications():
    """
    Cron job: Send all pending notifications that are due.

    Should be called every 5-10 minutes via Celery or Django-Q.
    """
    due_notifications = NotificationQueue.objects.filter(
        is_sent=False,
        scheduled_send_at__lte=timezone.now(),
    )

    employees = due_notifications.values_list("employee_id", flat=True).distinct()

    for employee_id in employees:
        try:
            from apps.accounts.models import Employee

            employee = Employee.objects.get(id=employee_id)
            send_notification_batch(employee)
        except Exception as e:
            logger.error("Error sending batch for employee %s: %s", employee_id, e)

    return len(employees)


# Convenience functions for common notifications

def notify_shift_assigned(shift, send_immediately=False):
    """Notify employee of a new shift assignment."""
    message = f"{shift.date.strftime('%a, %b %d')} | {shift.start_time} - {shift.end_time}"

    return queue_notification(
        employee=shift.employee,
        notification_type=NotificationQueue.NotificationType.SHIFT_ASSIGNED,
        message_body=message,
        related_object_id=shift.id,
        send_immediately=send_immediately,
    )


def notify_leave_approved(leave, send_immediately=True):
    """Notify employee of approved leave."""
    duration = (leave.end_date - leave.start_date).days + 1
    dates = (
        f"{leave.start_date.strftime('%b %d')}"
        if leave.start_date == leave.end_date
        else f"{leave.start_date.strftime('%b %d')} - {leave.end_date.strftime('%b %d')}"
    )

    message = f"Your leave ({dates}, {duration} day{'s' if duration > 1 else ''}) has been APPROVED ✓"

    return queue_notification(
        employee=leave.employee,
        notification_type=NotificationQueue.NotificationType.LEAVE_APPROVED,
        message_body=message,
        related_object_id=leave.id,
        send_immediately=send_immediately,
    )


def notify_leave_rejected(leave, send_immediately=True):
    """Notify employee of rejected leave."""
    dates = (
        f"{leave.start_date.strftime('%b %d')}"
        if leave.start_date == leave.end_date
        else f"{leave.start_date.strftime('%b %d')} - {leave.end_date.strftime('%b %d')}"
    )

    message = f"Your leave ({dates}) could not be approved due to staffing requirements. Contact your manager."

    return queue_notification(
        employee=leave.employee,
        notification_type=NotificationQueue.NotificationType.LEAVE_REJECTED,
        message_body=message,
        related_object_id=leave.id,
        send_immediately=send_immediately,
    )
