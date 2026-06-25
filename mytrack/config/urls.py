from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from mytrack.tracking.views_public import delivery_demo, delivery_location_api, delivery_track
from mytrack.tenancy.views import RoleAwareLoginView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", RoleAwareLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("mytrack.tracking.urls")),
    path("app/", include("mytrack.mobile.urls")),
    path("api/mobile/", include("mytrack.mobile.api_urls")),
    path("drivers/", include("mytrack.drivers.urls")),
    path("vehicles/", include("mytrack.vehicles.urls")),
    path("geofences/", include("mytrack.geofences.urls")),
    path("api/", include("mytrack.tracking.api_urls")),
    path("intelligence/", include("mytrack.intelligence.urls")),
    path("tenancy/", include("mytrack.tenancy.urls")),
    path("admin-panel/", include("mytrack.tenancy.admin_urls")),
    path("compliance/", include("mytrack.compliance.urls")),
    path("fuel/", include("mytrack.fuel.urls")),
    path("video/", include("mytrack.video_telematics.urls")),
    path("reporting/", include("mytrack.reporting.urls")),
    path("webhooks/", include("mytrack.webhooks.urls")),
    path("track/demo/", delivery_demo, name="delivery_demo"),
    path("track/<uuid:token>/", delivery_track, name="delivery_track"),
    path("api/track/<uuid:token>/", delivery_location_api, name="delivery_location_api"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
