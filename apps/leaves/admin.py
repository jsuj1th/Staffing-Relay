from django.contrib import admin
from .models import Leave


@admin.register(Leave)
class LeaveAdmin(admin.ModelAdmin):
    list_display = ["employee", "start_date", "end_date", "status", "created_at"]
    list_filter = ["status", "employee__employee_type", "employee__location"]
    search_fields = ["employee__name"]
    readonly_fields = ["ratio_before", "ratio_after", "internal_note", "created_at", "updated_at"]
    date_hierarchy = "start_date"
