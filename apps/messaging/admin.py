from django.contrib import admin
from .models import SmsLog


@admin.register(SmsLog)
class SmsLogAdmin(admin.ModelAdmin):
    list_display = ["from_phone", "employee", "inbound_msg", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["from_phone", "employee__name", "inbound_msg"]
    readonly_fields = ["from_phone", "employee", "inbound_msg", "outbound_msg", "leave", "created_at"]
