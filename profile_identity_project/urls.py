from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView

from identity.views import MetricsView, ValidateTokenView

RASTER_IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")


def media_serve(request, folder, path):
    """Serve uploaded media safely: uploads are untrusted and share the origin
    of the app, so anything that is not a raster image is forced to download
    and no response may be sniffed or run scripts. The document root is the
    public folder itself, so a path like feed_posts/../resumes/x cannot escape
    into the other (private) directories of MEDIA_ROOT."""
    response = serve(request, path, document_root=Path(settings.MEDIA_ROOT) / folder)
    if not response.get("Content-Type", "").startswith(RASTER_IMAGE_TYPES):
        response["Content-Disposition"] = "attachment"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response["X-Content-Type-Options"] = "nosniff"
    return response


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/", include("identity.urls")),
    path(
        "internal/auth/validate-token/",
        ValidateTokenView.as_view(),
        name="validate-token",
    ),
    path("internal/metrics/", MetricsView.as_view(), name="internal-metrics"),
    path("health/", include("identity.health_urls")),
]

# Profile pictures are served by the app itself (the gateway proxies
# /media/profile_pictures/ here); nothing else under MEDIA_ROOT is public. This
# must not depend on DEBUG, otherwise turning DEBUG off silently breaks every
# uploaded picture.
urlpatterns += [
    re_path(r"^media/(?P<folder>profile_pictures)/(?P<path>.*)$", media_serve),
]
