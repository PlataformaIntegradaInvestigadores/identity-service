"""Unitarias de identity/domain/policies.py: reglas de autorizacion puras."""

from django.test import TestCase

from identity.domain.exceptions import DomainPermissionDenied, DomainValidationError
from identity.domain.policies import (
    ensure_can_delete_group,
    ensure_can_delete_profile,
    ensure_can_edit_profile,
    ensure_can_edit_user,
    ensure_can_leave_group,
    ensure_can_remove_group_member,
    ensure_can_view_group,
)
from identity.models import Group, ProfileInformation, User


class PoliciesTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner@example.com", password="x", first_name="O", last_name="W"
        )
        self.other = User.objects.create_user(
            username="other@example.com", password="x", first_name="O", last_name="T"
        )


class TestEnsureCanEditUser(PoliciesTestCase):
    def test_mismo_usuario_no_lanza(self):
        ensure_can_edit_user(self.owner, self.owner)

    def test_otro_usuario_lanza_permission_denied(self):
        with self.assertRaises(DomainPermissionDenied):
            ensure_can_edit_user(self.other, self.owner)


class TestEnsureCanEditAndDeleteProfile(PoliciesTestCase):
    def _profile(self, **extra):
        return ProfileInformation.objects.create(user=self.owner, **extra)

    def test_dueno_puede_editar(self):
        ensure_can_edit_profile(self.owner, self._profile())

    def test_otro_no_puede_editar(self):
        with self.assertRaises(DomainPermissionDenied):
            ensure_can_edit_profile(self.other, self._profile())

    def test_dueno_puede_borrar_perfil_vacio(self):
        ensure_can_delete_profile(self.owner, self._profile())

    def test_no_puede_borrar_perfil_con_datos(self):
        profile = self._profile(about_me="hola")
        with self.assertRaises(DomainValidationError):
            ensure_can_delete_profile(self.owner, profile)

    def test_no_dueno_no_puede_borrar(self):
        with self.assertRaises(DomainPermissionDenied):
            ensure_can_delete_profile(self.other, self._profile())


class TestGroupPolicies(PoliciesTestCase):
    def _group(self):
        group = Group.objects.create(title="G", description="d", admin=self.owner)
        group.users.add(self.owner)
        return group

    def test_admin_puede_borrar_grupo(self):
        ensure_can_delete_group(self.owner, self._group())

    def test_no_admin_no_puede_borrar_grupo(self):
        with self.assertRaises(DomainPermissionDenied):
            ensure_can_delete_group(self.other, self._group())

    def test_no_admin_puede_salir_del_grupo(self):
        ensure_can_leave_group(self.other, self._group())

    def test_admin_no_puede_salir_debe_borrar(self):
        with self.assertRaises(DomainValidationError):
            ensure_can_leave_group(self.owner, self._group())

    def test_admin_ve_el_grupo(self):
        ensure_can_view_group(self.owner, self._group())

    def test_miembro_ve_el_grupo(self):
        group = self._group()
        group.users.add(self.other)
        ensure_can_view_group(self.other, group)

    def test_ajeno_no_ve_el_grupo(self):
        with self.assertRaises(DomainPermissionDenied):
            ensure_can_view_group(self.other, self._group())

    def test_admin_puede_remover_miembro(self):
        group = self._group()
        group.users.add(self.other)
        ensure_can_remove_group_member(self.owner, group, self.other)

    def test_no_admin_no_puede_remover_miembro(self):
        group = self._group()
        with self.assertRaises(DomainPermissionDenied):
            ensure_can_remove_group_member(self.other, group, self.owner)

    def test_admin_no_puede_removerse_a_si_mismo(self):
        group = self._group()
        with self.assertRaises(DomainValidationError):
            ensure_can_remove_group_member(self.owner, group, self.owner)
