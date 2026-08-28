"""Unitarias de identity/application/use_cases.py no cubiertas por los tests de
API existentes: update_user, create/delete_profile_information, delete_group,
leave_group y validate_group_visibility."""

from django.test import TestCase, override_settings

from identity.application.use_cases import (
    create_profile_information,
    delete_group,
    delete_profile_information,
    leave_group,
    update_user,
    validate_group_visibility,
)
from identity.domain.exceptions import DomainPermissionDenied
from identity.models import Group, ProfileInformation, User


@override_settings(LEGACY_SYNC_ENABLED=False)
class UseCasesTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner@example.com", password="x", first_name="O", last_name="W"
        )
        self.other = User.objects.create_user(
            username="other@example.com", password="x", first_name="O", last_name="T"
        )


class TestUpdateUser(UseCasesTestCase):
    def test_actualiza_los_campos_del_actor(self):
        updated = update_user(self.owner, self.owner, {"first_name": "Nuevo"})
        self.assertEqual(updated.first_name, "Nuevo")
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.first_name, "Nuevo")

    def test_no_puede_editar_a_otro(self):
        with self.assertRaises(DomainPermissionDenied):
            update_user(self.other, self.owner, {"first_name": "Hack"})


class TestCreateAndDeleteProfileInformation(UseCasesTestCase):
    def test_crea_perfil(self):
        profile = create_profile_information({"user": self.owner, "about_me": "hola"})
        self.assertTrue(ProfileInformation.objects.filter(pk=profile.pk).exists())

    def test_borra_perfil_vacio(self):
        profile = ProfileInformation.objects.create(user=self.owner)
        delete_profile_information(self.owner, profile)
        self.assertFalse(ProfileInformation.objects.filter(pk=profile.pk).exists())

    def test_no_puede_borrar_perfil_ajeno(self):
        profile = ProfileInformation.objects.create(user=self.owner)
        with self.assertRaises(DomainPermissionDenied):
            delete_profile_information(self.other, profile)


class TestDeleteAndLeaveGroup(UseCasesTestCase):
    def _group(self):
        group = Group.objects.create(title="G", description="d", admin=self.owner)
        group.users.add(self.owner)
        return group

    def test_admin_borra_el_grupo(self):
        group = self._group()
        group_id = group.id
        delete_group(self.owner, group)
        self.assertFalse(Group.objects.filter(id=group_id).exists())

    def test_no_admin_no_puede_borrar(self):
        with self.assertRaises(DomainPermissionDenied):
            delete_group(self.other, self._group())

    def test_no_admin_puede_dejar_el_grupo(self):
        group = self._group()
        group.users.add(self.other)
        leave_group(self.other, group)
        self.assertNotIn(self.other, group.users.all())


class TestValidateGroupVisibility(UseCasesTestCase):
    def test_miembro_puede_ver(self):
        group = Group.objects.create(title="G", description="d", admin=self.owner)
        group.users.add(self.owner)
        validate_group_visibility(self.owner, group)

    def test_ajeno_no_puede_ver(self):
        group = Group.objects.create(title="G", description="d", admin=self.owner)
        with self.assertRaises(DomainPermissionDenied):
            validate_group_visibility(self.other, group)
