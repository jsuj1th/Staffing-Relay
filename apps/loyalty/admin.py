from django.contrib import admin
from .models import LoyaltyPoint


@admin.register(LoyaltyPoint)
class LoyaltyPointAdmin(admin.ModelAdmin):
    list_display = ["employee", "points", "reason", "created_at"]
    list_filter = ["created_at"]
