from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView

from identity.views import MetricsView, ValidateTokenView

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

# Profile pictures are served by the app itself (the gateway proxies /media/
# here). This must not depend on DEBUG, otherwise turning DEBUG off in staging
# silently breaks every uploaded picture.
urlpatterns += [
    re_path(
        r"^media/(?P<path>.*)$",
        serve,
        {"document_root": settings.MEDIA_ROOT},
    ),
]
