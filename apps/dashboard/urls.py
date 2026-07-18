from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("employees/", views.employee_list, name="employees"),
    path("employees/new/", views.employee_create, name="employee_create"),
    path("employees/<int:pk>/", views.employee_detail, name="employee_detail"),
    path("employees/<int:pk>/edit/", views.employee_edit, name="employee_edit"),
    path("employees/<int:pk>/toggle-active/", views.employee_toggle_active, name="employee_toggle_active"),
    path("leaves/", views.leave_list, name="leaves"),
    path("leaves/new/", views.absence_create, name="absence_create"),
    path("leaves/<int:pk>/decision/", views.leave_decision, name="leave_decision"),
    path("leaves/<int:pk>/approve/", views.leave_approve, name="leave_approve"),
    path("leaves/<int:pk>/reject/", views.leave_reject, name="leave_reject"),
    path("leaves/<int:pk>/edit/", views.leave_edit, name="leave_edit"),
    path("shifts/", views.shift_day, name="shifts"),
    path("shifts/new/", views.shift_create, name="shift_create"),
    path("shifts/<int:pk>/edit/", views.shift_edit, name="shift_edit"),
    path("shifts/<int:pk>/delete/", views.shift_delete, name="shift_delete"),
    path("sms/", views.sms_log_list, name="sms_logs"),
    path("locations/<int:pk>/", views.location_detail, name="location_detail"),
]
