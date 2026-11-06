import logging

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, permissions
from rest_framework.parsers import FormParser, MultiPartParser

from ..domain.exceptions import (
    DomainRuleViolation,
)
from ..domain.policies import ensure_can_edit_user
from ..models import User
from ..openapi_docs import (
    FIELD_ERRORS,
    FORBIDDEN,
    NOT_FOUND,
    TAG_USERS,
    UNAUTHENTICATED,
    USER_PATH,
)
from ..serializers import (
    UserListSerializer,
    UserSerializer,
)
from .common import raise_drf_domain_exception

logger = logging.getLogger(__name__)


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
            "Edita los datos del propio usuario; solo se modifican los campos "
            "enviados. Se envía como `multipart/form-data` para poder subir la "
            "foto de perfil."
        ),
        parameters=[USER_PATH],
        responses={
            200: UserSerializer,
            400: FIELD_ERRORS,
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
    http_method_names = ["put", "options"]

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
    get=extend_schema(
        tags=[TAG_USERS],
        summary="Consultar un investigador",
        description=(
            "Devuelve los datos de perfil de un investigador por su ID. No "
            "requiere autenticación y solo encuentra cuentas de investigadores, "
            "no de empresas."
        ),
        parameters=[USER_PATH],
        responses={200: UserSerializer, 404: NOT_FOUND},
    )
)
class UserDetailView(generics.RetrieveAPIView):
    queryset = User.objects.filter(account_type=User.AccountType.RESEARCHER)
    serializer_class = UserSerializer
