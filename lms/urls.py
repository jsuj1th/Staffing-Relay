from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from apps.messaging.simulator import sms_simulator

urlpatterns = [
    path("admin/", admin.site.urls),
    path("dashboard/", include("apps.dashboard.urls")),
    path("webhooks/", include("apps.messaging.urls")),
    path("sms-simulator/", sms_simulator, name="sms_simulator"),
    path("health/", include("apps.dashboard.health_urls")),
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
]
