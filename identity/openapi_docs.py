"""Textos y serializers de documentación OpenAPI (Swagger) del servicio.

Solo describen el contrato; no participan en la lógica de las vistas.
"""

from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    PolymorphicProxySerializer,
)
from rest_framework import serializers

from .openapi_texts import (  # noqa: F401
    TAG_AUTH,
    TAG_GROUPS,
    TAG_MFA,
    TAG_PROFILE,
    TAG_USERS,
)

DEFAULT_RESPONSE_TEXT = {
    "200": "Operación exitosa.",
    "201": "Recurso creado.",
    "204": "Sin contenido.",
}
FORM_CONTENT_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")


def polish_schema(result, generator, request, public):
    """Postprocesado del schema: completa los textos de respuesta que
    drf-spectacular deja vacíos o en inglés y deja un solo formato de cuerpo
    por operación (JSON si existe; si no, multipart)."""
    for item in result.get("paths", {}).values():
        for operation in item.values():
            if not isinstance(operation, dict):
                continue
            for code, response in operation.get("responses", {}).items():
                if response.get("description") in (None, "", "No response body"):
                    response["description"] = DEFAULT_RESPONSE_TEXT.get(code, "")
            content = operation.get("requestBody", {}).get("content", {})
            if "application/json" in content:
                for media_type in FORM_CONTENT_TYPES:
                    content.pop(media_type, None)
            elif "multipart/form-data" in content:
                content.pop("application/x-www-form-urlencoded", None)
    return result


class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Mensaje legible del resultado o error.")


class LoginRequestSerializer(serializers.Serializer):
    username = serializers.EmailField(
        help_text="Correo con el que se registró la cuenta."
    )
    password = serializers.CharField(help_text="Contraseña de la cuenta.")


class SessionSerializer(serializers.Serializer):
    """Sesión iniciada. El `refresh` viaja en una cookie `HttpOnly`."""

    access = serializers.CharField(help_text="JWT de acceso.")
    user_type = serializers.ChoiceField(
        choices=["user", "company"], help_text="Tipo de cuenta autenticada."
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


class MfaChallengeSerializer(serializers.Serializer):
    """La cuenta debe completar el MFA antes de tener sesión."""

    status = serializers.ChoiceField(
        choices=["mfa_required", "mfa_enrollment_required"],
        help_text=(
            "`mfa_required`: la cuenta ya tiene MFA, falta el código. "
            "`mfa_enrollment_required`: la cuenta debe activar MFA primero."
        ),
    )
    mfa_challenge = serializers.CharField(
        help_text="Token de un solo uso para el paso de MFA."
    )
    expires_in = serializers.IntegerField(
        help_text="Segundos de vigencia del `mfa_challenge`."
    )


LOGIN_RESULT = PolymorphicProxySerializer(
    component_name="LoginResult",
    serializers=[SessionSerializer, MfaChallengeSerializer],
    resource_type_field_name=None,
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
    message = serializers.CharField(help_text="Confirmación del registro.")
    company_id = serializers.CharField(help_text="ID de la empresa creada.")
    company_name = serializers.CharField(help_text="Nombre de la empresa.")
    username = serializers.EmailField(help_text="Correo con el que inicia sesión.")
    industry = serializers.CharField(help_text="Sector de la empresa.")


GROUP_ID_PATH = OpenApiParameter(
    "id",
    location=OpenApiParameter.PATH,
    type=str,
    description="Identificador del grupo.",
)
USER_PATH = OpenApiParameter(
    "id",
    location=OpenApiParameter.PATH,
    type=str,
    description="Identificador del usuario.",
)
USER_ID_PATH = OpenApiParameter(
    "user_id",
    location=OpenApiParameter.PATH,
    type=str,
    description="Identificador del usuario a quitar del grupo.",
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
INVALID_CREDENTIALS = OpenApiResponse(
    DetailSerializer,
    description="Credenciales inválidas o cuenta bloqueada temporalmente.",
)
INVALID_REFRESH = OpenApiResponse(
    DetailSerializer,
    description="El refresh token es inválido, expiró o fue revocado.",
)
FORBIDDEN = OpenApiResponse(
    DetailSerializer, description="La cuenta no tiene permiso para esta acción."
)
NOT_FOUND = OpenApiResponse(DetailSerializer, description="El recurso no existe.")
BAD_REQUEST = OpenApiResponse(
    DetailSerializer, description="La petición no cumple una regla de negocio."
)
FIELD_ERRORS = OpenApiResponse(
    response={
        "type": "object",
        "additionalProperties": {"type": "array", "items": {"type": "string"}},
    },
    description="Datos inválidos: los errores vienen agrupados por campo.",
    examples=[
        OpenApiExample(
            "Campo inválido",
            value={"username": ["Ya existe una cuenta con este correo electrónico."]},
            response_only=True,
        )
    ],
)
