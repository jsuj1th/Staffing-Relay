"""Alert the admin contacts on every leave request and decision, each on the
channel they chose (email, SMS, or both).

Hooked to Leave's save signals, not to individual views — leaves are created and
decided from the SMS flow, the dashboard and Django admin, and all of them save.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from apps.leaves.models import Leave
from .sms import send_sms

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


def _email_body(leave):
    emp = leave.employee
    return "\n".join([
        f"Employee: {emp.name} ({emp.get_employee_type_display()})",
        f"Location: {emp.location.name if emp.location else '—'}",
        f"Phone:    {emp.phone}",
        f"Dates:    {_dates(leave)} ({leave.duration_days} day{'s' if leave.duration_days > 1 else ''})",
        f"Status:   {leave.get_status_display()}",
        f"Reason:   {leave.reason or '—'}",
        f"Note:     {leave.internal_note or '—'}",
        f"Decided by: {leave.approved_by or 'SMS / automatic'}",
    ])


def send_leave_alert(leave, event_status):
    """Notify every active admin contact. Returns (emails_sent, texts_sent)."""
    from .models import AdminContact, NotificationSetting

    if not NotificationSetting.load().leave_alerts_enabled:
        return 0, 0

    contacts = AdminContact.objects.filter(is_active=True)
    label = SUBJECTS.get(event_status, "Leave update")
    subject = f"[Relay] {label} — {leave.employee.name}"
    body = _email_body(leave)
    sms_text = (
        f"RELAY: {label} — {leave.employee.name}, "
        f"{_dates(leave)} ({leave.duration_days}d). Status: {leave.get_status_display()}."
    )

    emails = [c.email for c in contacts if c.wants_email]
    if emails:
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, emails, fail_silently=False)
        except Exception as e:  # a mail outage must never break the leave flow
            logger.error("Leave alert email failed (leave=%s): %s", leave.pk, e)
            emails = []

    texts = 0
    for contact in contacts:
        if contact.wants_sms and send_sms(contact.phone, sms_text):
            texts += 1

    if not emails and not texts:
        logger.info("Leave alert reached nobody (leave=%s) — check admin contacts", leave.pk)
    else:
        logger.info("Leave alert sent: leave=%s status=%s emails=%d texts=%d",
                    leave.pk, event_status, len(emails), texts)
    return len(emails), texts


@receiver(pre_save, sender=Leave)
def _stash_old_status(sender, instance, **kwargs):
    if instance.pk:
        instance._old_status = (
            sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        )


@receiver(post_save, sender=Leave)
def _notify_admins(sender, instance, created, **kwargs):
    if created or getattr(instance, "_old_status", instance.status) != instance.status:
        send_leave_alert(instance, instance.status)
