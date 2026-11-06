import logging

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import (
    AuthenticationFailed,
    InvalidToken,
    TokenError,
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from ..application.tokens import issue_session
from ..auth_sessions import revoke_session_for_refresh
from ..models import User
from ..openapi_docs import (
    BAD_REQUEST,
    FIELD_ERRORS,
    INVALID_CREDENTIALS,
    INVALID_REFRESH,
    LOGIN_RESULT,
    TAG_AUTH,
    CompanyRegisterResponseSerializer,
    LoginRequestSerializer,
    LogoutRequestSerializer,
    RefreshRequestSerializer,
    RefreshResponseSerializer,
    RegisterErrorSerializer,
)
from ..security_events import emit_security_event
from ..serializers import (
    CompanyRegisterSerializer,
    CompanyTokenObtainPairSerializer,
    RegisterSerializer,
    SessionTokenRefreshSerializer,
    UserTokenObtainPairSerializer,
)

logger = logging.getLogger(__name__)


@extend_schema_view(
    post=extend_schema(
        tags=[TAG_AUTH],
        summary="Iniciar sesión (investigador)",
        description=(
            "Autentica a un investigador con correo y contraseña. Si la sesión "
            "queda iniciada devuelve `access`, y el `refresh` viaja en una "
            "cookie `HttpOnly`. Si la cuenta usa o debe activar MFA devuelve "
            "`status` y un `mfa_challenge` para continuar en `/auth/mfa/`. "
            "Las credenciales inválidas y las cuentas bloqueadas responden el "
            "mismo error."
        ),
        request=LoginRequestSerializer,
        responses={200: LOGIN_RESULT, 401: INVALID_CREDENTIALS},
    )
)
class UserTokenObtainPairView(TokenObtainPairView):
    serializer_class = UserTokenObtainPairSerializer
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        raw_refresh = response.data.get("refresh")
        if raw_refresh:
            set_refresh_cookie(response, raw_refresh)
            response.data.pop("refresh", None)
        return response


@extend_schema_view(
    post=extend_schema(
        tags=[TAG_AUTH],
        summary="Iniciar sesión (empresa)",
        description=(
            "Igual que el inicio de sesión de investigadores, pero para cuentas "
            "de empresa. La respuesta incluye `company_id` en lugar de `user_id`."
        ),
        request=LoginRequestSerializer,
        responses={200: LOGIN_RESULT, 401: INVALID_CREDENTIALS},
    )
)
class CompanyTokenObtainPairView(UserTokenObtainPairView):
    serializer_class = CompanyTokenObtainPairSerializer


@extend_schema_view(
    post=extend_schema(
        tags=[TAG_AUTH],
        summary="Renovar el token de acceso",
        description=(
            "Intercambia un refresh token vigente por un nuevo `access`. Si no "
            "va en el cuerpo se toma de la cookie `HttpOnly`. El refresh se "
            "rota: el nuevo se entrega en la cookie y el anterior queda "
            "revocado."
        ),
        request=RefreshRequestSerializer,
        responses={200: RefreshResponseSerializer, 401: INVALID_REFRESH},
    )
)
class CustomTokenRefreshView(TokenRefreshView):
    serializer_class = SessionTokenRefreshSerializer
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        data = request.data.copy()
        if not data.get("refresh"):
            cookie_refresh = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
            if cookie_refresh:
                data["refresh"] = cookie_refresh
        serializer = self.get_serializer(data=data)
        try:
            serializer.is_valid(raise_exception=True)
        except AuthenticationFailed:
            emit_security_event(
                event_type="refresh_failed",
                severity="warning",
                outcome="failure",
                request=request,
                status_code=status.HTTP_401_UNAUTHORIZED,
                reason="invalid_or_inactive_refresh_session",
            )
            raise
        response = Response(serializer.validated_data, status=status.HTTP_200_OK)
        raw_refresh = response.data.get("refresh")
        if raw_refresh:
            set_refresh_cookie(response, raw_refresh)
            response.data.pop("refresh", None)
        auth_session = getattr(serializer, "auth_session", None)
        emit_security_event(
            event_type="refresh_success",
            severity="info",
            outcome="success",
            request=request,
            status_code=status.HTTP_200_OK,
            user=auth_session.user if auth_session else None,
            auth_session_id=str(auth_session.id) if auth_session else None,
        )
        return response


@extend_schema_view(
    post=extend_schema(
        tags=[TAG_AUTH],
        summary="Cerrar sesión",
        description=(
            "Revoca la sesión y el refresh token (del cuerpo o de la cookie) y "
            "borra la cookie. No requiere `access` válido."
        ),
        request=LogoutRequestSerializer,
        responses={204: None, 400: BAD_REQUEST},
    )
)
class LogoutView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        raw_refresh = request.data.get("refresh") or request.COOKIES.get(
            settings.JWT_REFRESH_COOKIE_NAME
        )
        if not raw_refresh:
            response = Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
            clear_refresh_cookie(response)
            emit_security_event(
                event_type="refresh_failed",
                severity="warning",
                outcome="failure",
                request=request,
                status_code=status.HTTP_400_BAD_REQUEST,
                reason="missing_refresh_on_logout",
            )
            return response
        try:
            session_revoked = revoke_session_for_refresh(raw_refresh)
            RefreshToken(raw_refresh).blacklist()
        except TokenError:
            response = Response(
                {"detail": "Invalid refresh token."}, status=status.HTTP_400_BAD_REQUEST
            )
            clear_refresh_cookie(response)
            emit_security_event(
                event_type="refresh_failed",
                severity="warning",
                outcome="failure",
                request=request,
                status_code=status.HTTP_400_BAD_REQUEST,
                reason="invalid_refresh_on_logout",
            )
            return response
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_refresh_cookie(response)
        if session_revoked:
            emit_security_event(
                event_type="session_revoked",
                severity="info",
                outcome="success",
                request=request,
                status_code=status.HTTP_204_NO_CONTENT,
            )
        emit_security_event(
            event_type="logout_success",
            severity="info",
            outcome="success",
            request=request,
            status_code=status.HTTP_204_NO_CONTENT,
        )
        return response


@extend_schema(exclude=True)
class ValidateTokenView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @staticmethod
    def _reject(request, status_code, detail, reason, user=None):
        emit_security_event(
            event_type="invalid_token",
            severity="warning",
            outcome="failure",
            request=request,
            status_code=status_code,
            user=user,
            reason=reason,
        )
        return Response({"detail": detail}, status=status_code)

    def get(self, request):
        try:
            authentication_result = JWTAuthentication().authenticate(request)
        except (AuthenticationFailed, InvalidToken, TokenError):
            return self._reject(
                request,
                status.HTTP_401_UNAUTHORIZED,
                "Invalid or expired token.",
                "invalid_or_expired_token",
            )
        if authentication_result is None:
            return self._reject(
                request,
                status.HTTP_401_UNAUTHORIZED,
                "Authentication credentials were not provided.",
                "missing_token",
            )
        user, validated_token = authentication_result
        if not user or not user.is_authenticated:
            return self._reject(
                request,
                status.HTTP_401_UNAUTHORIZED,
                "Invalid token user.",
                "invalid_token_user",
            )
        if not user.is_active:
            return self._reject(
                request,
                status.HTTP_403_FORBIDDEN,
                "Inactive user.",
                "inactive_user",
                user=user,
            )

        response = Response(status=status.HTTP_204_NO_CONTENT)
        response["X-Authenticated-User-Id"] = str(user.id)
        response["X-Authenticated-Token-Type"] = str(
            validated_token.get("token_type", "")
        )
        emit_security_event(
            event_type="token_validated",
            severity="info",
            outcome="success",
            request=request,
            status_code=status.HTTP_204_NO_CONTENT,
            user=user,
        )
        return response


def issue_final_auth_response(*, user, request, extra_data=None):
    issued = issue_session(user=user, request=request, mfa_verified=True)

    response_data = {"access": issued.access, **issued.principal}
    if extra_data:
        response_data.update(extra_data)

    response = Response(response_data, status=status.HTTP_200_OK)
    set_refresh_cookie(response, issued.refresh)
    return response


def set_refresh_cookie(response, raw_refresh):
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        raw_refresh,
        max_age=settings.JWT_REFRESH_COOKIE_MAX_AGE,
        httponly=settings.JWT_REFRESH_COOKIE_HTTPONLY,
        secure=settings.JWT_REFRESH_COOKIE_SECURE,
        samesite=settings.JWT_REFRESH_COOKIE_SAMESITE,
        path=settings.JWT_REFRESH_COOKIE_PATH,
        domain=settings.JWT_REFRESH_COOKIE_DOMAIN,
    )


def clear_refresh_cookie(response):
    response.delete_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        path=settings.JWT_REFRESH_COOKIE_PATH,
        samesite=settings.JWT_REFRESH_COOKIE_SAMESITE,
        domain=settings.JWT_REFRESH_COOKIE_DOMAIN,
    )


@extend_schema_view(
    post=extend_schema(
        tags=[TAG_AUTH],
        summary="Registrar un investigador",
        description=(
            "Crea una cuenta de investigador. La contraseña pasa las "
            "validaciones de seguridad de Django y el correo debe ser único."
        ),
        responses={
            201: RegisterSerializer,
            400: OpenApiResponse(
                RegisterErrorSerializer,
                description="Datos inválidos; los errores vienen por campo.",
            ),
        },
    )
)
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            emit_security_event(
                event_type="user_registered",
                severity="info",
                outcome="success",
                request=request,
                status_code=status.HTTP_201_CREATED,
                user=serializer.instance,
            )
            return Response(
                serializer.data, status=status.HTTP_201_CREATED, headers=headers
            )
        except ValidationError:
            if "password" in serializer.errors:
                emit_security_event(
                    event_type="password_rejected",
                    severity="warning",
                    outcome="failure",
                    request=request,
                    status_code=status.HTTP_400_BAD_REQUEST,
                    reason="password_validation_failed",
                    username=request.data.get("username"),
                )
            return Response(
                {"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception:
            logger.exception("User registration failed")
            return Response(
                {"error": "No se pudo completar el registro."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


@extend_schema_view(
    post=extend_schema(
        tags=[TAG_AUTH],
        summary="Registrar una empresa",
        description=(
            "Crea una cuenta de empresa con su perfil. `confirm_password` debe "
            "coincidir con `password`."
        ),
        responses={201: CompanyRegisterResponseSerializer, 400: FIELD_ERRORS},
    )
)
class CompanyRegisterView(generics.CreateAPIView):
    serializer_class = CompanyRegisterSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company_account = serializer.save()
        return Response(
            {
                "message": "Empresa registrada exitosamente",
                "company_id": company_account.id,
                "company_name": serializer.validated_data["company_name"],
                "username": company_account.username,
                "industry": serializer.validated_data.get("industry", "other"),
            },
            status=status.HTTP_201_CREATED,
        )
