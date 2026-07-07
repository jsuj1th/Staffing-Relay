from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("employees/", views.employee_list, name="employees"),
    path("employees/new/", views.employee_create, name="employee_create"),
    path("employees/<int:pk>/edit/", views.employee_edit, name="employee_edit"),
    path("leaves/", views.leave_list, name="leaves"),
    path("leaves/<int:pk>/decision/", views.leave_decision, name="leave_decision"),
    path("shifts/", views.shift_day, name="shifts"),
    path("shifts/new/", views.shift_create, name="shift_create"),
    path("shifts/<int:pk>/edit/", views.shift_edit, name="shift_edit"),
    path("shifts/<int:pk>/delete/", views.shift_delete, name="shift_delete"),
    path("sms/", views.sms_log_list, name="sms_logs"),
    path("locations/<int:pk>/", views.location_detail, name="location_detail"),
]
