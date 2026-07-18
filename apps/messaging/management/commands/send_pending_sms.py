from django.core.management.base import BaseCommand

from apps.messaging.notifications import send_all_pending_notifications


class Command(BaseCommand):
    help = "Flush the notification queue: send all batched SMS that are now due. Run every ~5 min via cron."

    def handle(self, *args, **options):
        count = send_all_pending_notifications()
        self.stdout.write(self.style.SUCCESS(f"Flushed batched SMS for {count} employee(s)."))
