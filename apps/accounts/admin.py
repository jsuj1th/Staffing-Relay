from django.contrib import admin
from .models import Employee


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ["name", "employee_type", "phone", "location", "is_active"]
    list_filter = ["employee_type", "location", "is_active"]
    search_fields = ["name", "phone"]
    list_editable = ["is_active"]
