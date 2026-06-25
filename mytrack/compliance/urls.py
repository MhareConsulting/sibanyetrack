from django.urls import path

from . import views

urlpatterns = [
    path('scorecard/',                  views.driver_scorecard,  name='compliance-scorecard'),
    path('hours/',                      views.hours_of_service,  name='compliance-hours'),
    path('inspections/',                views.inspection_list,   name='inspection-list'),
    path('inspections/new/',            views.inspection_create, name='inspection-create'),
    path('inspections/<int:log_id>/',   views.inspection_detail, name='inspection-detail'),
    path('documents/',                  views.document_list,     name='document-list'),
    path('documents/upload/',           views.document_upload,   name='document-upload'),
    path('documents/<int:doc_id>/delete/', views.document_delete, name='document-delete'),

    path('service/',                         views.service_list,      name='service-list'),
    path('service/new/',                     views.service_create,    name='service-create'),
    path('service/<int:pk>/edit/',           views.service_edit,      name='service-edit'),
    path('service/<int:pk>/done/',           views.service_mark_done, name='service-mark-done'),
    path('service/<int:pk>/delete/',         views.service_delete,    name='service-delete'),
]
