"""Unitarias de identity/legacy_sync.py: sincronizacion best-effort hacia el
monolito legacy, con cola de reintentos (outbox) ante fallos."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests
from django.test import TestCase, override_settings
from django.utils import timezone

from identity.legacy_sync import (
    LegacySyncClient,
    enqueue_legacy_sync,
    retry_outbox_item,
    send_legacy_sync,
)
from identity.models import LegacySyncOutbox


@override_settings(LEGACY_SYNC_ENABLED=False)
class TestSyncDeshabilitado(TestCase):
    def test_send_legacy_sync_retorna_true_sin_llamar_a_requests(self):
        with patch("identity.legacy_sync.requests.post") as mock_post:
            assert send_legacy_sync("/x", {}) is True
        mock_post.assert_not_called()

    def test_client_post_retorna_true_sin_llamar_a_requests(self):
        client = LegacySyncClient()
        with patch("identity.legacy_sync.requests.post") as mock_post:
            assert client.post("/x", {}) is True
        mock_post.assert_not_called()


@override_settings(
    LEGACY_SYNC_ENABLED=True,
    LEGACY_SYNC_BASE_URL="http://legacy.local",
    LEGACY_SYNC_TOKEN="tok",
)
class TestSendLegacySyncHabilitado(TestCase):
    def test_200_retorna_true(self):
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        with patch("identity.legacy_sync.requests.post", return_value=mock_resp):
            assert send_legacy_sync("/x", {"a": 1}) is True

    def test_410_retorado_como_completado_sin_reintento(self):
        mock_resp = MagicMock(status_code=410)
        with patch("identity.legacy_sync.requests.post", return_value=mock_resp):
            assert send_legacy_sync("/x", {"a": 1}) is True
        self.assertEqual(LegacySyncOutbox.objects.count(), 0)

    def test_fallo_de_red_encola_en_outbox_por_defecto(self):
        with patch(
            "identity.legacy_sync.requests.post",
            side_effect=requests.ConnectionError("down"),
        ):
            result = send_legacy_sync("/x", {"a": 1})
        self.assertFalse(result)
        self.assertEqual(LegacySyncOutbox.objects.count(), 1)
        item = LegacySyncOutbox.objects.first()
        self.assertEqual(item.status, LegacySyncOutbox.Status.PENDING)

    def test_fallo_de_red_sin_enqueue_on_failure_no_encola(self):
        with patch(
            "identity.legacy_sync.requests.post",
            side_effect=requests.ConnectionError("down"),
        ):
            result = send_legacy_sync("/x", {"a": 1}, enqueue_on_failure=False)
        self.assertFalse(result)
        self.assertEqual(LegacySyncOutbox.objects.count(), 0)


class TestEnqueueLegacySync(TestCase):
    def test_crea_registro_pending_en_outbox(self):
        enqueue_legacy_sync("/x", {"a": 1}, "boom")
        item = LegacySyncOutbox.objects.get()
        self.assertEqual(item.status, LegacySyncOutbox.Status.PENDING)
        self.assertEqual(item.last_error, "boom")
        self.assertEqual(item.payload, {"a": 1})


@override_settings(
    LEGACY_SYNC_ENABLED=True,
    LEGACY_SYNC_BASE_URL="http://legacy.local",
    LEGACY_SYNC_TOKEN="tok",
    LEGACY_SYNC_RETRY_DELAY=timedelta(minutes=5),
)
class TestRetryOutboxItem(TestCase):
    def _item(self):
        return LegacySyncOutbox.objects.create(
            path="/x",
            payload={"a": 1},
            status=LegacySyncOutbox.Status.PENDING,
            next_retry_at=timezone.now(),
        )

    def test_exito_marca_completado(self):
        item = self._item()
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        with patch("identity.legacy_sync.requests.post", return_value=mock_resp):
            result = retry_outbox_item(item)
        item.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(item.status, LegacySyncOutbox.Status.COMPLETED)
        self.assertIsNotNone(item.completed_at)
        self.assertEqual(item.last_error, "")

    def test_fallo_marca_failed_y_agenda_siguiente_reintento(self):
        item = self._item()
        with patch(
            "identity.legacy_sync.requests.post",
            side_effect=requests.ConnectionError("down"),
        ):
            result = retry_outbox_item(item)
        item.refresh_from_db()
        self.assertFalse(result)
        self.assertEqual(item.status, LegacySyncOutbox.Status.FAILED)
        self.assertEqual(item.attempts, 1)
        self.assertGreater(item.next_retry_at, timezone.now())

    def test_excepcion_inesperada_marca_failed_con_el_error(self):
        item = self._item()
        with patch(
            "identity.legacy_sync.requests.post", side_effect=ValueError("boom")
        ):
            result = retry_outbox_item(item)
        item.refresh_from_db()
        self.assertFalse(result)
        self.assertEqual(item.status, LegacySyncOutbox.Status.FAILED)
        self.assertEqual(item.last_error, "boom")
