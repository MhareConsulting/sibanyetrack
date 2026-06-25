from django.urls import path
from . import views

urlpatterns = [
    path("depot/switch/", views.depot_switch, name="depot-switch"),
    path("settings/", views.org_settings, name="org-settings"),
    path("audit/", views.audit_log_view, name="audit-log"),
    path("2fa/setup/", views.setup_2fa, name="2fa-setup"),
    path("2fa/verify/", views.verify_2fa, name="2fa-verify"),
    path("2fa/disable/", views.disable_2fa, name="2fa-disable"),
]
