from django.urls import path
from .views_admin import (
    admin_applications,
    admin_org_detail,
    admin_user_create,
    admin_user_edit,
    admin_user_search,
)

urlpatterns = [
    path("", admin_applications, name="admin-applications"),
    path("users/", admin_user_search, name="admin-user-search"),
    path("users/add/", admin_user_create, name="admin-user-create"),
    path("users/<int:pk>/edit/", admin_user_edit, name="admin-user-edit"),
    path("organisations/<int:pk>/", admin_org_detail, name="admin-org-detail"),
]
