import logging

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, permissions, status
from rest_framework.response import Response

from ..application.use_cases import (
    delete_group,
    leave_group,
    remove_group_member,
    validate_group_visibility,
)
from ..domain.exceptions import (
    DomainRuleViolation,
)
from ..models import Group, User
from ..openapi_docs import (
    BAD_REQUEST,
    FIELD_ERRORS,
    FORBIDDEN,
    GROUP_ID_PATH,
    NOT_FOUND,
    TAG_GROUPS,
    UNAUTHENTICATED,
    USER_ID_PATH,
    USER_PATH,
    DetailSerializer,
)
from ..serializers import (
    GroupDetailSerializer,
    GroupSerializer,
    UserGroupSerializer,
    UserListSerializer,
)
from .common import raise_drf_domain_exception

logger = logging.getLogger(__name__)


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
        responses={201: GroupSerializer, 400: FIELD_ERRORS, 401: UNAUTHENTICATED},
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
        parameters=[GROUP_ID_PATH],
        responses={
            204: None,
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
        parameters=[GROUP_ID_PATH],
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
        parameters=[USER_PATH],
        responses={200: UserListSerializer, 401: UNAUTHENTICATED, 404: NOT_FOUND},
    )
)
class GroupMemberDetailView(generics.RetrieveAPIView):
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
        parameters=[GROUP_ID_PATH],
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
        parameters=[GROUP_ID_PATH, USER_ID_PATH],
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
