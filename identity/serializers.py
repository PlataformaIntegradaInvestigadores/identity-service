from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)

from .application.authentication import MFAStep, authenticate_credentials
from .application.mfa import (
    MFAChallengeRejected,
    begin_enrollment,
    confirm_enrollment,
    verify_login_code,
)
from .application.tokens import build_refresh_token, issue_session
from .application.use_cases import (
    create_group,
    create_profile_information,
    register_company,
    register_user,
    update_profile_information,
    update_user,
)
from .auth_sessions import get_active_session_for_refresh, rotate_auth_session
from .domain.exceptions import AuthenticationRejected
from .mfa_services import GENERIC_MFA_ERROR
from .models import Group, ProfileInformation, User, UserMFASettings
from .profile_services import normalize_contact_info


class UserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "username"]
        extra_kwargs = {
            "id": {"help_text": "Identificador del usuario."},
            "first_name": {"help_text": "Nombres."},
            "last_name": {"help_text": "Apellidos."},
            "username": {"help_text": "Correo electrónico de la cuenta."},
        }


class UserTokenObtainPairSerializer(TokenObtainPairSerializer):
    expected_account_type = User.AccountType.RESEARCHER

    @classmethod
    def get_token(cls, user):
        return build_refresh_token(user)

    def validate(self, attrs):
        request = self.context.get("request")
        try:
            step = authenticate_credentials(
                username=attrs.get(self.username_field),
                password=attrs.get("password"),
                account_type=self.expected_account_type,
                request=request,
            )
        except AuthenticationRejected as exc:
            raise AuthenticationFailed(str(exc), code="authorization") from exc

        if isinstance(step, MFAStep):
            return {
                "status": step.status,
                "mfa_challenge": step.challenge_token,
                "expires_in": step.expires_in,
            }

        self.user = step.user
        issued = issue_session(user=self.user, request=request, mfa_verified=False)
        return {"refresh": issued.refresh, "access": issued.access, **issued.principal}


class CompanyTokenObtainPairSerializer(UserTokenObtainPairSerializer):
    expected_account_type = User.AccountType.COMPANY


class MFASetupSerializer(serializers.Serializer):
    mfa_challenge = serializers.CharField(
        write_only=True,
        trim_whitespace=True,
        help_text="Token de un solo uso recibido al iniciar sesión.",
    )

    def save(self, **kwargs):
        try:
            started = begin_enrollment(
                raw_challenge=self.validated_data["mfa_challenge"],
                request=self.context.get("request"),
            )
        except MFAChallengeRejected as exc:
            raise _mfa_validation_error(exc) from exc
        self.user = started.user
        return {
            "otpauth_uri": started.secret.otpauth_uri,
            "manual_key": started.secret.secret,
            "qr_code": started.secret.qr_data_uri,
        }


class _MFACodeSerializer(serializers.Serializer):
    mfa_challenge = serializers.CharField(
        write_only=True,
        trim_whitespace=True,
        help_text="Token de un solo uso recibido al iniciar sesión.",
    )
    code = serializers.CharField(
        write_only=True,
        trim_whitespace=True,
        help_text="Código de 6 dígitos de la app autenticadora.",
    )

    def validate(self, attrs):
        attrs["code"] = _normalize_totp_code_or_error(attrs.get("code"))
        return attrs

    def check_code(self, use_case):
        try:
            self.user = use_case(
                raw_challenge=self.validated_data["mfa_challenge"],
                code=self.validated_data["code"],
                request=self.context.get("request"),
            )
        except MFAChallengeRejected as exc:
            raise _mfa_validation_error(exc) from exc
        return self.user


class MFAConfirmSerializer(_MFACodeSerializer):
    def save(self, **kwargs):
        user = self.check_code(confirm_enrollment)
        return {"detail": "MFA enabled successfully", "user": user}


class MFAVerifySerializer(_MFACodeSerializer):
    def save(self, **kwargs):
        return {"user": self.check_code(verify_login_code)}


class MFAStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserMFASettings
        fields = ["mfa_enabled", "mfa_confirmed_at"]
        read_only_fields = fields
        extra_kwargs = {
            "mfa_enabled": {"help_text": "Si la cuenta tiene MFA activo."},
            "mfa_confirmed_at": {
                "help_text": "Fecha en que se confirmó el MFA; nula si no está activo."
            },
        }


def _normalize_totp_code_or_error(code: str) -> str:
    normalized_code = str(code or "").replace(" ", "").strip()
    if len(normalized_code) != 6 or not normalized_code.isdigit():
        raise _mfa_validation_error()
    return normalized_code


def _mfa_validation_error(exc=None):
    return serializers.ValidationError({"detail": str(exc or GENERIC_MFA_ERROR)})


class SessionTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        request = self.context.get("request")
        try:
            session = get_active_session_for_refresh(attrs["refresh"])
        except TokenError as exc:
            raise AuthenticationFailed(
                "Refresh token session is not active.", code="token_not_valid"
            ) from exc
        if session is None:
            raise AuthenticationFailed(
                "Refresh token session is not active.", code="token_not_valid"
            )
        self.auth_session = session

        data = super().validate(attrs)
        rotated_refresh = data.get("refresh")
        if rotated_refresh:
            rotate_auth_session(
                session=session, raw_refresh_token=rotated_refresh, request=request
            )
        else:
            session.last_seen_at = timezone.now()
            session.save(update_fields=["last_seen_at"])
        return data


class RelativeImageField(serializers.ImageField):
    def to_representation(self, value):
        if not value:
            return None
        try:
            return value.url
        except ValueError:
            return None


class UserSerializer(serializers.ModelSerializer):
    profile_picture = RelativeImageField(
        required=False,
        allow_null=True,
        help_text="Foto de perfil; en las respuestas es la ruta relativa de la imagen.",
    )

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "scopus_id",
            "institution",
            "website",
            "investigation_camp",
            "profile_picture",
            "email_institution",
            "interests",
        ]
        extra_kwargs = {
            "first_name": {"help_text": "Nombres."},
            "last_name": {"help_text": "Apellidos."},
            "scopus_id": {"help_text": "ID de autor en Scopus."},
            "institution": {"help_text": "Institución a la que pertenece."},
            "website": {
                "help_text": "Sitio web personal; se antepone `http://` si falta."
            },
            "investigation_camp": {"help_text": "Campo de investigación."},
            "email_institution": {"help_text": "Correo institucional."},
            "interests": {"help_text": "Intereses de investigación, en texto libre."},
        }

    def validate_website(self, value):
        if value and not value.startswith(("http://", "https://")):
            value = "http://" + value
        return value

    def update(self, instance, validated_data):
        request = self.context.get("request")
        actor = request.user if request else instance
        return update_user(actor, instance, validated_data)


class UserDetailSerializer(serializers.ModelSerializer):
    profile_picture = RelativeImageField(
        read_only=True, help_text="Ruta relativa de la foto de perfil."
    )

    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "username",
            "scopus_id",
            "investigation_camp",
            "institution",
            "email_institution",
            "website",
            "profile_picture",
            "is_active",
            "is_staff",
        ]
        extra_kwargs = {
            "id": {"help_text": "Identificador del usuario."},
            "first_name": {"help_text": "Nombres."},
            "last_name": {"help_text": "Apellidos."},
            "username": {"help_text": "Correo electrónico de la cuenta."},
            "scopus_id": {"help_text": "ID de autor en Scopus."},
            "investigation_camp": {"help_text": "Campo de investigación."},
            "institution": {"help_text": "Institución a la que pertenece."},
            "email_institution": {"help_text": "Correo institucional."},
            "website": {"help_text": "Sitio web personal."},
            "is_active": {"help_text": "Si la cuenta está activa."},
            "is_staff": {"help_text": "Si la cuenta es de personal administrativo."},
        }


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        help_text="Contraseña; debe pasar las validaciones de seguridad de Django.",
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "username", "scopus_id", "password"]
        extra_kwargs = {
            "first_name": {"help_text": "Nombres."},
            "last_name": {"help_text": "Apellidos."},
            "username": {"help_text": "Correo electrónico; debe ser único."},
            "scopus_id": {"help_text": "ID de autor en Scopus (opcional)."},
        }

    def validate(self, attrs):
        user = User(
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
            username=attrs.get("username", ""),
            scopus_id=attrs.get("scopus_id"),
        )
        try:
            validate_password(attrs.get("password"), user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data):
        return register_user(validated_data)

    def validate_username(self, value):
        normalized = User.objects.normalize_email(value)
        if User.objects.filter(
            username__iexact=normalized,
            account_type=User.AccountType.RESEARCHER,
        ).exists():
            raise serializers.ValidationError(
                "Ya existe un investigador con este correo electrónico."
            )
        return normalized


class CompanyRegisterSerializer(serializers.Serializer):
    company_name = serializers.CharField(
        max_length=200, help_text="Nombre de la empresa."
    )
    username = serializers.EmailField(help_text="Correo con el que iniciará sesión.")
    password = serializers.CharField(
        write_only=True, min_length=8, help_text="Contraseña (mínimo 8 caracteres)."
    )
    confirm_password = serializers.CharField(
        write_only=True, help_text="Debe coincidir con `password`."
    )
    industry = serializers.CharField(
        max_length=20, default="other", help_text="Sector de la empresa."
    )
    description = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Descripción de la empresa.",
    )
    website = serializers.URLField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Sitio web de la empresa.",
    )
    phone = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Teléfono de contacto.",
    )
    address = serializers.CharField(
        max_length=300,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Dirección.",
    )
    founded_year = serializers.IntegerField(
        required=False, allow_null=True, help_text="Año de fundación."
    )
    employee_count = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Rango de empleados (por ejemplo, `11-50`).",
    )

    def validate_company_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("El nombre de la empresa es requerido.")
        return value

    def validate_username(self, value):
        normalized = User.objects.normalize_email(value)
        if User.objects.filter(
            username__iexact=normalized,
            account_type=User.AccountType.COMPANY,
        ).exists():
            raise serializers.ValidationError(
                "Ya existe una cuenta con este correo electrónico."
            )
        return normalized

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("confirm_password"):
            raise serializers.ValidationError(
                {"confirm_password": "Las contraseñas no coinciden."}
            )
        candidate = User(
            username=attrs["username"],
            first_name="",
            last_name="",
            account_type=User.AccountType.COMPANY,
        )
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data):
        return register_company(validated_data)


@extend_schema_field(
    {
        "type": "array",
        "items": {"type": "string"},
        "example": ["Inteligencia artificial", "Bioinformática"],
    }
)
class DisciplinesField(serializers.JSONField):
    """Lista de disciplinas; solo cambia cómo se documenta el campo."""


@extend_schema_field(
    {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "example": "phone"},
                "value": {"type": "string", "example": "+593 99 999 9999"},
            },
        },
    }
)
class ContactInfoField(serializers.JSONField):
    """Lista de medios de contacto `{type, value}`; solo cambia la documentación."""


class ProfileInformationSerializer(serializers.ModelSerializer):
    disciplines = DisciplinesField(
        required=False, help_text="Disciplinas o áreas de especialidad."
    )
    contact_info = ContactInfoField(
        required=False,
        help_text="Medios de contacto; cada uno tiene `type` y `value`.",
    )

    class Meta:
        model = ProfileInformation
        fields = ["about_me", "disciplines", "contact_info"]
        extra_kwargs = {"about_me": {"help_text": "Presentación personal."}}

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["disciplines"] = data.get("disciplines") or []
        data["contact_info"] = normalize_contact_info(data.get("contact_info"))
        return data

    def validate_contact_info(self, value):
        return normalize_contact_info(value)

    def update(self, instance, validated_data):
        request = self.context.get("request")
        actor = request.user if request else instance.user
        return update_profile_information(actor, instance, validated_data)

    def create(self, validated_data):
        return create_profile_information(validated_data)


class GroupSerializer(serializers.ModelSerializer):
    users = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(account_type=User.AccountType.RESEARCHER),
        many=True,
        required=False,
        help_text="IDs de los investigadores que integran el grupo.",
    )

    class Meta:
        model = Group
        fields = ["id", "title", "description", "admin_id", "users", "voting_type"]
        extra_kwargs = {
            "id": {"help_text": "Identificador del grupo."},
            "title": {"help_text": "Nombre del grupo."},
            "description": {"help_text": "Descripción del grupo."},
            "admin_id": {"help_text": "ID del administrador del grupo."},
            "users": {"help_text": "IDs de los integrantes del grupo."},
            "voting_type": {"help_text": "Modalidad de votación del grupo."},
        }
        read_only_fields = ["id", "admin"]

    def create(self, validated_data):
        request = self.context.get("request")
        return create_group(request.user, validated_data)


class UserGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ["id", "title", "description", "admin_id", "users", "voting_type"]
        extra_kwargs = {
            "id": {"help_text": "Identificador del grupo."},
            "title": {"help_text": "Nombre del grupo."},
            "description": {"help_text": "Descripción del grupo."},
            "admin_id": {"help_text": "ID del administrador del grupo."},
            "users": {"help_text": "IDs de los integrantes del grupo."},
            "voting_type": {"help_text": "Modalidad de votación del grupo."},
        }
        read_only_fields = [
            "id",
            "title",
            "description",
            "admin_id",
            "users",
            "voting_type",
        ]


class GroupDetailSerializer(serializers.ModelSerializer):
    users = UserDetailSerializer(
        many=True, read_only=True, help_text="Integrantes del grupo."
    )

    class Meta:
        model = Group
        fields = ["id", "title", "description", "admin_id", "users", "voting_type"]
        extra_kwargs = {
            "id": {"help_text": "Identificador del grupo."},
            "title": {"help_text": "Nombre del grupo."},
            "description": {"help_text": "Descripción del grupo."},
            "admin_id": {"help_text": "ID del administrador del grupo."},
            "users": {"help_text": "IDs de los integrantes del grupo."},
            "voting_type": {"help_text": "Modalidad de votación del grupo."},
        }
        read_only_fields = ["id", "admin_id"]
