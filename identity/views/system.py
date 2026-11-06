import logging
import socket

from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from ..metrics import prometheus_metrics_response

logger = logging.getLogger(__name__)


def _local_ip() -> str:
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "unknown"


@extend_schema(exclude=True)
class HealthLiveView(APIView):
    permission_classes = [permissions.AllowAny]
    renderer_classes = [JSONRenderer]

    def get(self, request):
        try:
            connection.ensure_connection()
            db_status = "ok"
        except Exception:
            logger.exception("Health check DB failure")
            db_status = "error"

        ok = db_status == "ok"
        payload = {
            "server_name": "identity-service",
            "ip_address": _local_ip(),
            "global_status": "Online" if ok else "Offline",
            "groups": [
                {
                    "group_name": "Identidad y Autenticación",
                    "group_status": "Operativo" if ok else "Caído",
                    "services": [{"name": "postgresql", "status": db_status}],
                }
            ],
        }
        return Response(payload, status=200 if ok else 503)


@extend_schema(exclude=True)
class MetricsView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return prometheus_metrics_response()
