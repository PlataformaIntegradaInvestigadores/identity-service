"""Textos y serializers de documentación OpenAPI (Swagger) del servicio.

Solo describen el contrato; no participan en la lógica de las vistas.
"""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import serializers

from .openapi_texts import (  # noqa: F401
    TAG_AUTH,
    TAG_GROUPS,
    TAG_MFA,
    TAG_PROFILE,
    TAG_USERS,
)


class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Mensaje legible del resultado o error.")


class LoginResponseSerializer(serializers.Serializer):
    """Respuesta de inicio de sesión; los campos presentes dependen del caso."""

    status = serializers.ChoiceField(
        choices=["mfa_required", "mfa_enrollment_required"],
        required=False,
        help_text="Solo aparece si falta completar el MFA.",
    )
    mfa_challenge = serializers.CharField(
        required=False,
        help_text="Token de un solo uso para el paso de MFA. Solo si hay `status`.",
    )
    expires_in = serializers.IntegerField(
        required=False,
        help_text="Segundos de vigencia del `mfa_challenge`. Solo si hay `status`.",
    )
    access = serializers.CharField(
        required=False, help_text="JWT de acceso. Solo si la sesión quedó iniciada."
    )
    user_type = serializers.ChoiceField(
        choices=["user", "company"],
        required=False,
        help_text="Tipo de cuenta autenticada.",
    )
    user_id = serializers.CharField(
        required=False, help_text="ID del investigador (`user_type` = `user`)."
    )
    company_id = serializers.CharField(
        required=False, help_text="ID de la empresa (`user_type` = `company`)."
    )
    detail = serializers.CharField(
        required=False, help_text="Mensaje adicional (por ejemplo, tras confirmar MFA)."
    )


class RefreshRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField(
        required=False,
        help_text="Refresh token. Si se omite se usa el de la cookie `HttpOnly`.",
    )


class RefreshResponseSerializer(serializers.Serializer):
    access = serializers.CharField(help_text="Nuevo JWT de acceso.")


class LogoutRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField(
        required=False,
        help_text="Refresh token a revocar. Si se omite se usa el de la cookie.",
    )


class MFASetupResponseSerializer(serializers.Serializer):
    otpauth_uri = serializers.CharField(
        help_text="URI `otpauth://` para registrar la cuenta en la app autenticadora."
    )
    manual_key = serializers.CharField(
        help_text="Clave en texto para ingresar a mano si no se puede escanear el QR."
    )
    qr_code = serializers.CharField(help_text="Imagen del QR como data URI (PNG).")


class RegisterErrorSerializer(serializers.Serializer):
    errors = serializers.DictField(
        help_text="Errores de validación agrupados por campo."
    )


class CompanyRegisterResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    company_id = serializers.CharField()
    company_name = serializers.CharField()
    username = serializers.EmailField(help_text="Correo con el que inicia sesión.")
    industry = serializers.CharField()


ID_PATH = OpenApiParameter(
    "id",
    location=OpenApiParameter.PATH,
    type=str,
    description="Identificador del recurso.",
)
USER_ID_PATH = OpenApiParameter(
    "user_id",
    location=OpenApiParameter.PATH,
    type=str,
    description="Identificador del usuario.",
)
PROFILE_USER_ID_PATH = OpenApiParameter(
    "user__id",
    location=OpenApiParameter.PATH,
    type=str,
    description="Identificador del usuario dueño del perfil.",
)

UNAUTHENTICATED = OpenApiResponse(
    DetailSerializer, description="Falta el token o es inválido o expiró."
)
FORBIDDEN = OpenApiResponse(
    DetailSerializer, description="La cuenta no tiene permiso para esta acción."
)
NOT_FOUND = OpenApiResponse(DetailSerializer, description="El recurso no existe.")
BAD_REQUEST = OpenApiResponse(
    DetailSerializer, description="Datos inválidos o la regla de negocio no se cumple."
)
