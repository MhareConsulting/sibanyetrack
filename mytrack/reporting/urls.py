from django.urls import path

from . import views


urlpatterns = [
    path("", views.reporting_home, name="reporting-home"),
    path("common/<str:domain>/", views.common_report, name="reporting-common"),
    path("custom/", views.custom_builder, name="reporting-custom-builder"),
    path("custom/<int:report_id>/run/", views.run_custom_report, name="reporting-run-custom"),
    path("custom/runs/<int:run_id>/export/", views.export_custom_report, name="reporting-export-custom"),
    path("templates/save/", views.save_report_template, name="reporting-template-save"),
    path("templates/<int:pk>/load/", views.load_report_template, name="reporting-template-load"),
    path("templates/<int:pk>/delete/", views.delete_report_template, name="reporting-template-delete"),
    path("schedules/", views.report_schedule_list, name="reporting-schedules"),
    path("schedules/create/", views.report_schedule_create, name="reporting-schedule-create"),
    path("schedules/<int:pk>/delete/", views.report_schedule_delete, name="reporting-schedule-delete"),
]
