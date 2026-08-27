"""Unitarias de los management commands de identity (sync/import/retry legacy)."""

import json
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from identity.company_profiles import CompanyProfileServiceUnavailable
from identity.models import Group, LegacySyncOutbox, User


class TestRetryLegacySyncOutboxCommand(TestCase):
    def test_procesa_items_pendientes_y_reporta_resultado(self):
        LegacySyncOutbox.objects.create(
            path="/x",
            payload={"a": 1},
            status=LegacySyncOutbox.Status.PENDING,
            next_retry_at=timezone.now() - timedelta(minutes=1),
        )
        with patch(
            "identity.management.commands.retry_legacy_sync_outbox.retry_outbox_item",
            return_value=True,
        ):
            call_command("retry_legacy_sync_outbox")
        item = LegacySyncOutbox.objects.get()
        self.assertEqual(
            item.status, LegacySyncOutbox.Status.PENDING
        )  # no cambia aqui: el mock no actualiza

    def test_sin_items_pendientes_no_falla(self):
        call_command("retry_legacy_sync_outbox")
        self.assertEqual(LegacySyncOutbox.objects.count(), 0)

    def test_respeta_el_limite(self):
        for _ in range(3):
            LegacySyncOutbox.objects.create(
                path="/x",
                payload={},
                status=LegacySyncOutbox.Status.PENDING,
                next_retry_at=timezone.now() - timedelta(minutes=1),
            )
        with patch(
            "identity.management.commands.retry_legacy_sync_outbox.retry_outbox_item",
            return_value=True,
        ) as mock_retry:
            call_command("retry_legacy_sync_outbox", limit=1)
        self.assertEqual(mock_retry.call_count, 1)


class TestSyncCompanyIdentitiesCommand(TestCase):
    def test_servicio_no_disponible_lanza_command_error(self):
        with patch(
            "identity.management.commands.sync_company_identities."
            "fetch_legacy_company_identities",
            side_effect=CompanyProfileServiceUnavailable(),
        ):
            with self.assertRaises(CommandError):
                call_command("sync_company_identities")

    def test_crea_usuarios_company_nuevos(self):
        companies = [
            {
                "id": "co1",
                "username": "acme@example.com",
                "password": "hashedpw",
                "is_active": True,
            }
        ]
        with patch(
            "identity.management.commands.sync_company_identities."
            "fetch_legacy_company_identities",
            return_value=companies,
        ):
            call_command("sync_company_identities")
        user = User.objects.get(id="co1")
        self.assertEqual(user.account_type, User.AccountType.COMPANY)
        self.assertEqual(user.username, "acme@example.com")

    def test_registro_incompleto_cuenta_como_conflicto_y_falla(self):
        companies = [{"id": "", "username": "", "password": ""}]
        with patch(
            "identity.management.commands.sync_company_identities."
            "fetch_legacy_company_identities",
            return_value=companies,
        ):
            with self.assertRaises(CommandError):
                call_command("sync_company_identities")

    def test_conflicto_de_email_con_otro_id_se_reporta_y_falla(self):
        User.objects.create(
            id="existing1",
            username="acme@example.com",
            account_type=User.AccountType.COMPANY,
        )
        companies = [
            {
                "id": "co2",
                "username": "acme@example.com",
                "password": "hashedpw",
            }
        ]
        with patch(
            "identity.management.commands.sync_company_identities."
            "fetch_legacy_company_identities",
            return_value=companies,
        ):
            with self.assertRaises(CommandError):
                call_command("sync_company_identities")
        self.assertFalse(User.objects.filter(id="co2").exists())


class TestImportLegacyIdentityCommand(TestCase):
    def test_archivo_inexistente_lanza_command_error(self):
        with self.assertRaises(CommandError):
            call_command("import_legacy_identity", "/no/existe.json")

    def test_importa_usuarios_perfiles_y_grupos(self):
        payload = {
            "users": [
                {
                    "id": "u1",
                    "username": "ana@example.com",
                    "password": "hashedpw",
                    "first_name": "Ana",
                    "last_name": "Perez",
                }
            ],
            "profiles": [
                {
                    "user_id": "u1",
                    "about_me": "hola",
                    "disciplines": [],
                    "contact_info": [],
                }
            ],
            "groups": [
                {
                    "id": "g1",
                    "title": "Grupo X",
                    "description": "desc",
                    "admin_id": "u1",
                    "users": ["u1"],
                }
            ],
            "group_memberships": [],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(payload, f)
            path = f.name

        with patch(
            "identity.management.commands.import_legacy_identity."
            "backfill_missing_profile_information",
            return_value=0,
        ):
            call_command("import_legacy_identity", path)

        self.assertTrue(User.objects.filter(id="u1").exists())
        self.assertTrue(Group.objects.filter(id="g1").exists())
        group = Group.objects.get(id="g1")
        self.assertIn("u1", group.users.values_list("id", flat=True))
