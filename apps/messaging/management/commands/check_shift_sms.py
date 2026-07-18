from django.core.management.base import BaseCommand
from apps.shifts.models import Shift
from apps.messaging.models import NotificationQueue, SmsLog
from datetime import date


class Command(BaseCommand):
    help = "Check if SMS notification has been sent for a shift"

    def add_arguments(self, parser):
        parser.add_argument("shift_id", type=int, help="Shift ID to check")

    def handle(self, *args, **options):
        shift_id = options["shift_id"]

        try:
            shift = Shift.objects.get(id=shift_id)
        except Shift.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Shift {shift_id} not found"))
            return

        self.stdout.write(f"\n📍 Shift: {shift.employee.name}")
        self.stdout.write(f"   Date: {shift.date} | Time: {shift.start_time} - {shift.end_time}\n")

        # Check notification queue
        notification = NotificationQueue.objects.filter(
            related_object_id=shift.id,
            notification_type=NotificationQueue.NotificationType.SHIFT_ASSIGNED,
        ).first()

        if notification:
            status = "✅ SENT" if notification.is_sent else "⏳ PENDING"
            self.stdout.write(f"Notification Status: {status}")
            self.stdout.write(f"Message: {notification.message_body}")
            self.stdout.write(f"Queued at: {notification.created_at}")
            self.stdout.write(f"Scheduled to send: {notification.scheduled_send_at}")
            if notification.is_sent:
                self.stdout.write(f"Sent at: {notification.sent_at}")
        else:
            self.stdout.write(self.style.WARNING("⚠️  No notification queued for this shift"))

        # Check SMS log
        self.stdout.write("\n")
        sms_log = SmsLog.objects.filter(employee=shift.employee).order_by("-created_at").first()
        if sms_log:
            self.stdout.write(f"Latest SMS to {sms_log.from_phone}:")
            self.stdout.write(f"  Message: {sms_log.outbound_msg[:150]}...")
            self.stdout.write(f"  Sent: {sms_log.created_at}")
        else:
            self.stdout.write("No SMS logs found for this employee")

        self.stdout.write("\n")
