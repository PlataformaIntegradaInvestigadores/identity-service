"""Unitarias de identity/profile_services.py: normalizacion de contact_info y
backfill de perfiles faltantes."""

from django.test import TestCase, override_settings

from identity.models import User
from identity.profile_services import (
    backfill_missing_profile_information,
    normalize_contact_info,
)


class TestNormalizeContactInfo(TestCase):
    def test_lista_se_devuelve_igual(self):
        value = [{"type": "email", "value": "a@b.com"}]
        self.assertEqual(normalize_contact_info(value), value)

    def test_vacio_o_none_retorna_lista_vacia(self):
        self.assertEqual(normalize_contact_info(None), [])
        self.assertEqual(normalize_contact_info(""), [])
        self.assertEqual(normalize_contact_info({}), [])

    def test_dict_con_type_y_value_se_envuelve_en_lista(self):
        value = {"type": "email", "value": "a@b.com"}
        self.assertEqual(normalize_contact_info(value), [value])

    def test_dict_generico_se_convierte_a_lista_de_items(self):
        value = {"email": "a@b.com", "phone": ""}
        result = normalize_contact_info(value)
        self.assertEqual(result, [{"type": "email", "value": "a@b.com"}])

    def test_otro_tipo_retorna_lista_vacia(self):
        self.assertEqual(normalize_contact_info(123), [])


@override_settings(LEGACY_SYNC_ENABLED=False)
class TestBackfillMissingProfileInformation(TestCase):
    def test_crea_perfiles_para_usuarios_sin_perfil(self):
        User.objects.create_user(
            username="a@example.com", password="x", first_name="A", last_name="B"
        )
        User.objects.create_user(
            username="b@example.com", password="x", first_name="C", last_name="D"
        )
        created = backfill_missing_profile_information(sync_legacy=False)
        self.assertEqual(created, 2)

    def test_no_crea_si_ya_tienen_perfil(self):
        backfill_missing_profile_information(sync_legacy=False)
        self.assertEqual(backfill_missing_profile_information(sync_legacy=False), 0)
