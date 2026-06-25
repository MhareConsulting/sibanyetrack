from django.urls import path
from . import views

urlpatterns = [
    path('', views.webhook_list, name='webhook-list'),
    path('create/', views.webhook_create, name='webhook-create'),
    path('<int:pk>/delete/', views.webhook_delete, name='webhook-delete'),
    path('<int:pk>/toggle/', views.webhook_toggle, name='webhook-toggle'),
]
