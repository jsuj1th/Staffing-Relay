"""Email the admin contacts on every leave request and decision.

Hooked to Leave's save signals, not to individual views — leaves are created and
decided from the SMS flow, the dashboard and Django admin, and all of them save.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from apps.leaves.models import Leave

logger = logging.getLogger(__name__)

SUBJECTS = {
    Leave.Status.PENDING: "Leave requested",
    Leave.Status.APPROVED: "Leave approved",
    Leave.Status.EXTREME: "Leave approved (extreme coverage)",
    Leave.Status.REJECTED: "Leave rejected",
    Leave.Status.CANCELLED: "Leave cancelled",
}


def _dates(leave):
    if leave.start_date == leave.end_date:
        return leave.start_date.strftime("%b %d, %Y")
    return f"{leave.start_date:%b %d, %Y} – {leave.end_date:%b %d, %Y}"


def send_leave_email(leave, event_status):
    """Send one leave notification to the configured admin contacts."""
    from .models import NotificationSetting

    setting = NotificationSetting.load()
    if not setting.leave_email_enabled:
        return False
    recipients = setting.recipient_list
    if not recipients:
        logger.info("Leave email skipped: no admin recipients configured (leave=%s)", leave.pk)
        return False

    emp = leave.employee
    subject = f"[Relay] {SUBJECTS.get(event_status, 'Leave update')} — {emp.name}"
    body = "\n".join([
        f"Employee: {emp.name} ({emp.get_employee_type_display()})",
        f"Location: {emp.location.name if emp.location else '—'}",
        f"Phone:    {emp.phone}",
        f"Dates:    {_dates(leave)} ({leave.duration_days} day{'s' if leave.duration_days > 1 else ''})",
        f"Status:   {leave.get_status_display()}",
        f"Reason:   {leave.reason or '—'}",
        f"Note:     {leave.internal_note or '—'}",
        f"Decided by: {leave.approved_by or 'SMS / automatic'}",
    ])

    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=False)
    except Exception as e:  # a mail outage must never break the leave flow
        logger.error("Leave email failed (leave=%s): %s", leave.pk, e)
        return False
    logger.info("Leave email sent: leave=%s status=%s to=%s", leave.pk, event_status, recipients)
    return True


@receiver(pre_save, sender=Leave)
def _stash_old_status(sender, instance, **kwargs):
    if instance.pk:
        instance._old_status = (
            sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        )


@receiver(post_save, sender=Leave)
def _notify_admins(sender, instance, created, **kwargs):
    if created:
        send_leave_email(instance, instance.status)
    elif getattr(instance, "_old_status", instance.status) != instance.status:
        send_leave_email(instance, instance.status)
