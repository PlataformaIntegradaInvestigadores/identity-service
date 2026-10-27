import logging
import socket

from django.conf import settings
from django.db import connection
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.renderers import JSONRenderer
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

from .application.use_cases import (
    delete_group,
    delete_profile_information,
    leave_group,
    remove_group_member,
    validate_group_visibility,
)
from .auth_sessions import create_auth_session, revoke_session_for_refresh
from .domain.exceptions import (
    DomainPermissionDenied,
    DomainRuleViolation,
    DomainValidationError,
)
from .domain.policies import ensure_can_edit_user
from .metrics import prometheus_metrics_response
from .models import Group, ProfileInformation, User, UserMFASettings
from .openapi_docs import (
    BAD_REQUEST,
    FORBIDDEN,
    ID_PATH,
    NOT_FOUND,
    PROFILE_USER_ID_PATH,
    TAG_AUTH,
    TAG_GROUPS,
    TAG_MFA,
    TAG_PROFILE,
    TAG_USERS,
    UNAUTHENTICATED,
    USER_ID_PATH,
    CompanyRegisterResponseSerializer,
    DetailSerializer,
    LoginResponseSerializer,
    LogoutRequestSerializer,
    MFASetupResponseSerializer,
    RefreshRequestSerializer,
    RefreshResponseSerializer,
    RegisterErrorSerializer,
)
from .profile_services import ensure_profile_information
from .security_events import emit_security_event
from .serializers import (
    CompanyRegisterSerializer,
    CompanyTokenObtainPairSerializer,
    GroupDetailSerializer,
    GroupSerializer,
    MFAConfirmSerializer,
    MFASetupSerializer,
    MFAStatusSerializer,
    MFAVerifySerializer,
    ProfileInformationSerializer,
    RegisterSerializer,
    SessionTokenRefreshSerializer,
    UserGroupSerializer,
    UserListSerializer,
    UserSerializer,
    UserTokenObtainPairSerializer,
)

logger = logging.getLogger(__name__)


def raise_drf_domain_exception(exc):
    if isinstance(exc, DomainPermissionDenied):
        raise PermissionDenied(str(exc)) from exc
    if isinstance(exc, DomainValidationError):
        raise ValidationError({"detail": str(exc)}) from exc
    raise exc


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


@extend_schema_view(
    get=extend_schema(
        tags=[TAG_USERS],
        summary="Listar investigadores",
        description=(
            "Devuelve las cuentas de investigadores, sin incluir a quien hace la "
            "petición. Sirve para buscar integrantes al armar un grupo."
        ),
        responses={200: UserListSerializer(many=True), 401: UNAUTHENTICATED},
    )
)
class UserListView(generics.ListAPIView):
    serializer_class = UserListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(account_type=User.AccountType.RESEARCHER).exclude(
            id=self.request.user.id
        )


@extend_schema_view(
    put=extend_schema(
        tags=[TAG_USERS],
        summary="Actualizar datos de un usuario",
        description=(
            "Edita los datos del propio usuario. La actualización es siempre "
            "parcial: solo se modifican los campos enviados, igual que con "
            "`PATCH`. Se envía como `multipart/form-data` para poder subir la "
            "foto de perfil."
        ),
        responses={
            200: UserSerializer,
            400: BAD_REQUEST,
            401: UNAUTHENTICATED,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    ),
    patch=extend_schema(
        tags=[TAG_USERS],
        summary="Actualizar parcialmente un usuario",
        description=(
            "Edita los campos enviados del propio usuario. Se envía como "
            "`multipart/form-data` para poder subir la foto de perfil."
        ),
        responses={
            200: UserSerializer,
            400: BAD_REQUEST,
            401: UNAUTHENTICATED,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    ),
)
class UserUpdateView(generics.UpdateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    def get_object(self):
        obj = super().get_object()
        try:
            ensure_can_edit_user(self.request.user, obj)
        except DomainRuleViolation as exc:
            raise_drf_domain_exception(exc)
        return obj

    def update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        try:
            return super().update(request, *args, **kwargs)
        except DomainRuleViolation as exc:
            raise_drf_domain_exception(exc)


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
        responses={200: LoginResponseSerializer, 401: UNAUTHENTICATED},
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
        responses={200: LoginResponseSerializer, 401: UNAUTHENTICATED},
    )
)
class CompanyTokenObtainPairView(UserTokenObtainPairView):
    serializer_class = CompanyTokenObtainPairSerializer


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
        responses={200: LoginResponseSerializer, 400: BAD_REQUEST},
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
        responses={200: LoginResponseSerializer, 400: BAD_REQUEST},
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
        responses={200: RefreshResponseSerializer, 401: UNAUTHENTICATED},
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

    def get(self, request):
        try:
            authentication_result = JWTAuthentication().authenticate(request)
        except (AuthenticationFailed, InvalidToken, TokenError):
            emit_security_event(
                event_type="invalid_token",
                severity="warning",
                outcome="failure",
                request=request,
                status_code=status.HTTP_401_UNAUTHORIZED,
                reason="invalid_or_expired_token",
            )
            return Response(
                {"detail": "Invalid or expired token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if authentication_result is None:
            emit_security_event(
                event_type="invalid_token",
                severity="warning",
                outcome="failure",
                request=request,
                status_code=status.HTTP_401_UNAUTHORIZED,
                reason="missing_token",
            )
            return Response(
                {"detail": "Authentication credentials were not provided."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        user, validated_token = authentication_result
        if not user or not user.is_authenticated:
            emit_security_event(
                event_type="invalid_token",
                severity="warning",
                outcome="failure",
                request=request,
                status_code=status.HTTP_401_UNAUTHORIZED,
                reason="invalid_token_user",
            )
            return Response(
                {"detail": "Invalid token user."}, status=status.HTTP_401_UNAUTHORIZED
            )
        if not user.is_active:
            emit_security_event(
                event_type="invalid_token",
                severity="warning",
                outcome="failure",
                request=request,
                status_code=status.HTTP_403_FORBIDDEN,
                user=user,
                reason="inactive_user",
            )
            return Response(
                {"detail": "Inactive user."}, status=status.HTTP_403_FORBIDDEN
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
    refresh = UserTokenObtainPairSerializer.get_token(user)
    refresh["email"] = user.username
    refresh["mfa"] = True
    raw_refresh = str(refresh)

    auth_session = create_auth_session(
        user=user, raw_refresh_token=raw_refresh, request=request
    )

    if user.account_type == User.AccountType.COMPANY:
        principal_data = {"company_id": user.id, "user_type": "company"}
    else:
        principal_data = {"user_id": user.id, "user_type": "user"}
    response_data = {"access": str(refresh.access_token), **principal_data}
    if extra_data:
        response_data.update(extra_data)

    response = Response(response_data, status=status.HTTP_200_OK)
    set_refresh_cookie(response, raw_refresh)
    emit_security_event(
        event_type="login_success",
        severity="info",
        outcome="success",
        request=request,
        status_code=status.HTTP_200_OK,
        user=user,
        auth_session_id=str(auth_session.id),
    )
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
    get=extend_schema(
        tags=[TAG_USERS],
        summary="Consultar un investigador",
        description=(
            "Devuelve los datos de perfil de un investigador por su ID. No "
            "requiere autenticación y solo encuentra cuentas de investigadores, "
            "no de empresas."
        ),
        responses={200: UserSerializer, 404: NOT_FOUND},
    )
)
class UserDetailView(generics.RetrieveAPIView):
    queryset = User.objects.filter(account_type=User.AccountType.RESEARCHER)
    serializer_class = UserSerializer


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
        except Exception as exc:
            return Response(
                {"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema_view(
    post=extend_schema(
        tags=[TAG_AUTH],
        summary="Registrar una empresa",
        description=(
            "Crea una cuenta de empresa con su perfil. `confirm_password` debe "
            "coincidir con `password`."
        ),
        responses={201: CompanyRegisterResponseSerializer, 400: BAD_REQUEST},
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
                "company_name": serializer.company_name,
                "username": company_account.username,
                "industry": serializer.industry,
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    get=extend_schema(
        tags=[TAG_PROFILE],
        operation_id="profile_information_me_retrieve",
        summary="Consultar mi perfil",
        description=(
            "Devuelve la información de perfil de la cuenta autenticada. Si "
            "aún no existe se crea vacía."
        ),
        responses={200: ProfileInformationSerializer, 401: UNAUTHENTICATED},
    ),
    put=extend_schema(
        tags=[TAG_PROFILE],
        summary="Reemplazar mi perfil",
        description="Reemplaza la información de perfil de la cuenta autenticada.",
        responses={
            200: ProfileInformationSerializer,
            400: BAD_REQUEST,
            401: UNAUTHENTICATED,
            403: FORBIDDEN,
        },
    ),
    patch=extend_schema(
        tags=[TAG_PROFILE],
        summary="Actualizar mi perfil",
        description="Modifica solo los campos enviados del perfil.",
        responses={
            200: ProfileInformationSerializer,
            400: BAD_REQUEST,
            401: UNAUTHENTICATED,
            403: FORBIDDEN,
        },
    ),
    delete=extend_schema(
        tags=[TAG_PROFILE],
        summary="Eliminar mi perfil",
        description=(
            "Borra la información de perfil de la cuenta autenticada. Solo es "
            "posible si todos sus campos están vacíos; si no, responde `400`."
        ),
        responses={
            204: None,
            400: BAD_REQUEST,
            401: UNAUTHENTICATED,
            403: FORBIDDEN,
        },
    ),
)
class ProfileInformationDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ProfileInformation.objects.all()
    serializer_class = ProfileInformationSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_object(self):
        return ensure_profile_information(self.request.user)

    def perform_update(self, serializer):
        try:
            serializer.save()
        except DomainRuleViolation as exc:
            raise_drf_domain_exception(exc)

    def perform_destroy(self, instance):
        try:
            delete_profile_information(self.request.user, instance)
        except DomainRuleViolation as exc:
            raise_drf_domain_exception(exc)


@extend_schema_view(
    get=extend_schema(
        tags=[TAG_PROFILE],
        operation_id="profile_information_user_retrieve",
        summary="Consultar el perfil de un usuario",
        description=(
            "Devuelve la información de perfil pública de un usuario por su ID."
        ),
        parameters=[PROFILE_USER_ID_PATH],
        responses={200: ProfileInformationSerializer, 404: NOT_FOUND},
    )
)
class PublicProfileInformationDetailView(generics.RetrieveAPIView):
    queryset = ProfileInformation.objects.all()
    serializer_class = ProfileInformationSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "user__id"

    def get_object(self):
        user = get_object_or_404(User, id=self.kwargs["user__id"])
        return ensure_profile_information(user)


@extend_schema_view(
    get=extend_schema(
        tags=[TAG_GROUPS],
        summary="Listar grupos",
        description="Devuelve todos los grupos de investigación.",
        responses={200: GroupSerializer(many=True), 401: UNAUTHENTICATED},
    ),
    post=extend_schema(
        tags=[TAG_GROUPS],
        summary="Crear un grupo",
        description=(
            "Crea un grupo cuyo administrador es la cuenta autenticada. "
            "`users` es la lista de IDs de investigadores que lo integran."
        ),
        responses={201: GroupSerializer, 400: BAD_REQUEST, 401: UNAUTHENTICATED},
    ),
)
class GroupListCreateView(generics.ListCreateAPIView):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAuthenticated]


@extend_schema_view(
    get=extend_schema(
        tags=[TAG_GROUPS],
        summary="Listar mis grupos",
        description=(
            "Devuelve los grupos de los que forma parte la cuenta autenticada."
        ),
        responses={200: UserGroupSerializer(many=True), 401: UNAUTHENTICATED},
    )
)
class UserGroupsListView(generics.ListAPIView):
    serializer_class = UserGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Group.objects.filter(users=self.request.user)


@extend_schema_view(
    delete=extend_schema(
        tags=[TAG_GROUPS],
        summary="Eliminar un grupo",
        description="Elimina el grupo. Solo puede hacerlo su administrador.",
        responses={
            204: None,
            400: BAD_REQUEST,
            401: UNAUTHENTICATED,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    )
)
class GroupDeleteView(generics.DestroyAPIView):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        group = self.get_object()
        try:
            delete_group(request.user, group)
        except DomainRuleViolation as exc:
            raise_drf_domain_exception(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    post=extend_schema(
        tags=[TAG_GROUPS],
        summary="Salir de un grupo",
        description=(
            "La cuenta autenticada deja el grupo indicado. El administrador no "
            "puede salir: debe eliminar el grupo."
        ),
        request=None,
        responses={
            200: DetailSerializer,
            400: BAD_REQUEST,
            401: UNAUTHENTICATED,
            404: NOT_FOUND,
        },
    )
)
class GroupLeaveView(generics.GenericAPIView):
    queryset = Group.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        group = self.get_object()
        try:
            leave_group(request.user, group)
        except DomainRuleViolation as exc:
            raise_drf_domain_exception(exc)
        return Response(
            {"detail": "You have left the group."}, status=status.HTTP_200_OK
        )


@extend_schema_view(
    get=extend_schema(
        tags=[TAG_GROUPS],
        summary="Consultar un integrante de grupo",
        description=(
            "Devuelve nombre y correo de un investigador, para mostrarlo como "
            "integrante de un grupo."
        ),
        responses={200: UserListSerializer, 401: UNAUTHENTICATED, 404: NOT_FOUND},
    )
)
class UserDetailViewtoGroup(generics.RetrieveAPIView):
    queryset = User.objects.filter(account_type=User.AccountType.RESEARCHER)
    serializer_class = UserListSerializer
    permission_classes = [permissions.IsAuthenticated]


@extend_schema_view(
    get=extend_schema(
        tags=[TAG_GROUPS],
        summary="Consultar un grupo",
        description=(
            "Devuelve el grupo con los datos de sus integrantes. Solo pueden "
            "verlo quienes forman parte de él."
        ),
        responses={
            200: GroupDetailSerializer,
            401: UNAUTHENTICATED,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    )
)
class GroupDetailView(generics.RetrieveAPIView):
    queryset = Group.objects.all()
    serializer_class = GroupDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        group = self.get_object()
        try:
            validate_group_visibility(request.user, group)
        except DomainRuleViolation as exc:
            raise_drf_domain_exception(exc)
        return Response(self.get_serializer(group).data)


@extend_schema_view(
    delete=extend_schema(
        tags=[TAG_GROUPS],
        summary="Quitar a un integrante",
        description=(
            "El administrador del grupo expulsa a un integrante. No puede "
            "quitarse a sí mismo."
        ),
        parameters=[ID_PATH, USER_ID_PATH],
        responses={
            200: DetailSerializer,
            400: BAD_REQUEST,
            401: UNAUTHENTICATED,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    )
)
class RemoveMemberView(generics.GenericAPIView):
    queryset = Group.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        group = self.get_object()
        user_id = self.kwargs.get("user_id")
        try:
            user_to_remove = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "User does not exist."}, status=status.HTTP_404_NOT_FOUND
            )
        try:
            remove_group_member(request.user, group, user_to_remove)
        except DomainRuleViolation as exc:
            raise_drf_domain_exception(exc)
        return Response(
            {"detail": "Member removed successfully."}, status=status.HTTP_200_OK
        )
