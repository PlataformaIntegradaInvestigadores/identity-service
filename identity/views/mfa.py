import logging

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import UserMFASettings
from ..openapi_docs import (
    BAD_REQUEST,
    TAG_MFA,
    UNAUTHENTICATED,
    MFASetupResponseSerializer,
    SessionSerializer,
)
from ..security_events import emit_security_event
from ..serializers import (
    MFAConfirmSerializer,
    MFASetupSerializer,
    MFAStatusSerializer,
    MFAVerifySerializer,
)
from .auth import issue_final_auth_response

logger = logging.getLogger(__name__)


@extend_schema_view(
    post=extend_schema(
        tags=[TAG_MFA],
        summary="Iniciar la activación de MFA",
        description=(
            "Genera el secreto TOTP y el código QR para registrar la cuenta en "
            "una app autenticadora. Requiere el `mfa_challenge` de tipo "
            "`mfa_enrollment_required` obtenido al iniciar sesión."
        ),
        request=MFASetupSerializer,
        responses={200: MFASetupResponseSerializer, 400: BAD_REQUEST},
    )
)
class MFASetupView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = MFASetupSerializer(data=request.data, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
            data = serializer.save()
        except ValidationError:
            emit_security_event(
                event_type="mfa_setup_failed",
                severity="warning",
                outcome="failure",
                request=request,
                status_code=status.HTTP_400_BAD_REQUEST,
                reason="invalid_mfa_setup",
            )
            raise
        emit_security_event(
            event_type="mfa_setup_started",
            severity="info",
            outcome="pending",
            request=request,
            status_code=status.HTTP_200_OK,
            user=serializer.user,
        )
        return Response(data, status=status.HTTP_200_OK)


@extend_schema_view(
    post=extend_schema(
        tags=[TAG_MFA],
        summary="Confirmar la activación de MFA",
        description=(
            "Valida el primer código de la app autenticadora, deja el MFA "
            "activo e inicia la sesión: devuelve `access` y deja el `refresh` "
            "en la cookie."
        ),
        request=MFAConfirmSerializer,
        responses={200: SessionSerializer, 400: BAD_REQUEST},
    )
)
class MFAConfirmView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = MFAConfirmSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        emit_security_event(
            event_type="mfa_enabled",
            severity="info",
            outcome="success",
            request=request,
            status_code=status.HTTP_200_OK,
            user=result["user"],
        )
        return issue_final_auth_response(
            user=result["user"],
            request=request,
            extra_data={"detail": result["detail"]},
        )


@extend_schema_view(
    post=extend_schema(
        tags=[TAG_MFA],
        summary="Verificar el código MFA al iniciar sesión",
        description=(
            "Segundo paso del inicio de sesión para cuentas con MFA activo. "
            "Recibe el `mfa_challenge` de `mfa_required` y el código de 6 "
            "dígitos; devuelve `access` y deja el `refresh` en la cookie. "
            "Varios códigos erróneos bloquean el desafío y luego la cuenta."
        ),
        request=MFAVerifySerializer,
        responses={200: SessionSerializer, 400: BAD_REQUEST},
    )
)
class MFAVerifyView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = MFAVerifySerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        emit_security_event(
            event_type="mfa_success",
            severity="info",
            outcome="success",
            request=request,
            status_code=status.HTTP_200_OK,
            user=result["user"],
        )
        return issue_final_auth_response(user=result["user"], request=request)


@extend_schema_view(
    get=extend_schema(
        tags=[TAG_MFA],
        summary="Consultar el estado de MFA",
        description="Indica si la cuenta autenticada tiene MFA activo y desde cuándo.",
        responses={200: MFAStatusSerializer, 401: UNAUTHENTICATED},
    )
)
class MFAStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        mfa_settings, _ = UserMFASettings.objects.get_or_create(user=request.user)
        emit_security_event(
            event_type="mfa_status_checked",
            severity="info",
            outcome="success",
            request=request,
            status_code=status.HTTP_200_OK,
            user=request.user,
            mfa_enabled=mfa_settings.mfa_enabled,
        )
        return Response(
            MFAStatusSerializer(mfa_settings).data, status=status.HTTP_200_OK
        )
