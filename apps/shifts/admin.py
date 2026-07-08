from django.contrib import admin
from .models import Shift


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ["employee", "date", "start_time", "end_time", "created_by"]
    list_filter = ["date", "employee__location"]
    search_fields = ["employee__name"]
    date_hierarchy = "date"
