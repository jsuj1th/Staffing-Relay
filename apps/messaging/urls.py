from django.urls import path
from . import views
from .simulator import sms_simulator

urlpatterns = [
    path("telnyx/", views.telnyx_webhook, name="telnyx_webhook"),
    path("simulator/", sms_simulator, name="sms_simulator"),
]
