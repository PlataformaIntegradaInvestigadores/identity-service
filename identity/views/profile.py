import logging

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, permissions

from ..application.use_cases import (
    delete_profile_information,
)
from ..domain.exceptions import (
    DomainRuleViolation,
)
from ..models import ProfileInformation, User
from ..openapi_docs import (
    BAD_REQUEST,
    FIELD_ERRORS,
    FORBIDDEN,
    NOT_FOUND,
    PROFILE_USER_ID_PATH,
    TAG_PROFILE,
    UNAUTHENTICATED,
)
from ..profile_services import ensure_profile_information
from ..serializers import (
    ProfileInformationSerializer,
)
from .common import raise_drf_domain_exception

logger = logging.getLogger(__name__)


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
        summary="Actualizar mi perfil",
        description=(
            "Actualiza la información de perfil de la cuenta autenticada; solo "
            "se modifican los campos enviados."
        ),
        responses={
            200: ProfileInformationSerializer,
            400: FIELD_ERRORS,
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
    http_method_names = ["get", "put", "delete", "head", "options"]

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
