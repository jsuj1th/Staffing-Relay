from django.contrib import admin
from .models import Location, EmployeeLocation


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["name", "city", "state", "phone"]
    search_fields = ["name", "city"]


@admin.register(EmployeeLocation)
class EmployeeLocationAdmin(admin.ModelAdmin):
    list_display = ["employee", "location", "is_primary"]
    list_filter = ["location", "is_primary"]
