"""Unitarias de identity/company_profiles.py: cliente HTTP hacia el servicio
legacy de perfiles de empresa (provision + fetch)."""

from unittest.mock import MagicMock, patch

import requests
from django.test import TestCase, override_settings

from identity.company_profiles import (
    CompanyProfileConflict,
    CompanyProfileServiceUnavailable,
    fetch_legacy_company_identities,
    provision_company_profile,
)


@override_settings(
    COMPANY_PROFILE_SERVICE_URL="http://legacy.local",
    COMPANY_PROFILE_SYNC_TOKEN="secret-token",
)
class TestProvisionCompanyProfile(TestCase):
    def test_envia_payload_sin_password_ni_confirm_password(self):
        mock_resp = MagicMock(status_code=201)
        with patch(
            "identity.company_profiles.requests.post", return_value=mock_resp
        ) as mock_post:
            provision_company_profile(
                "abc123",
                {"name": "ACME", "password": "x", "confirm_password": "x"},
            )
        _, kwargs = mock_post.call_args
        assert "password" not in kwargs["json"]
        assert "confirm_password" not in kwargs["json"]
        assert kwargs["json"]["id"] == "abc123"
        assert kwargs["headers"]["X-Profile-Sync-Token"] == "secret-token"

    def test_conflicto_409_lanza_company_profile_conflict(self):
        mock_resp = MagicMock(status_code=409)
        with patch("identity.company_profiles.requests.post", return_value=mock_resp):
            with self.assertRaises(CompanyProfileConflict):
                provision_company_profile("abc123", {"name": "ACME"})

    def test_status_inesperado_lanza_service_unavailable(self):
        mock_resp = MagicMock(status_code=500)
        with patch("identity.company_profiles.requests.post", return_value=mock_resp):
            with self.assertRaises(CompanyProfileServiceUnavailable):
                provision_company_profile("abc123", {"name": "ACME"})

    def test_error_de_red_lanza_service_unavailable(self):
        with patch(
            "identity.company_profiles.requests.post",
            side_effect=requests.ConnectionError("down"),
        ):
            with self.assertRaises(CompanyProfileServiceUnavailable):
                provision_company_profile("abc123", {"name": "ACME"})


@override_settings(COMPANY_PROFILE_SERVICE_URL="", COMPANY_PROFILE_SYNC_TOKEN="")
class TestServiceNotConfigured(TestCase):
    def test_sin_url_ni_token_lanza_service_unavailable(self):
        with self.assertRaises(CompanyProfileServiceUnavailable):
            provision_company_profile("abc123", {"name": "ACME"})


@override_settings(
    COMPANY_PROFILE_SERVICE_URL="http://legacy.local",
    COMPANY_PROFILE_SYNC_TOKEN="secret-token",
)
class TestFetchLegacyCompanyIdentities(TestCase):
    def test_retorna_la_lista_de_companies(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"companies": [{"id": "1"}]}
        with patch("identity.company_profiles.requests.get", return_value=mock_resp):
            result = fetch_legacy_company_identities()
        assert result == [{"id": "1"}]

    def test_respuesta_sin_companies_retorna_lista_vacia(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {}
        with patch("identity.company_profiles.requests.get", return_value=mock_resp):
            assert fetch_legacy_company_identities() == []

    def test_error_de_red_lanza_service_unavailable(self):
        with patch(
            "identity.company_profiles.requests.get",
            side_effect=requests.Timeout("slow"),
        ):
            with self.assertRaises(CompanyProfileServiceUnavailable):
                fetch_legacy_company_identities()

    def test_json_invalido_lanza_service_unavailable(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = ValueError("bad json")
        with patch("identity.company_profiles.requests.get", return_value=mock_resp):
            with self.assertRaises(CompanyProfileServiceUnavailable):
                fetch_legacy_company_identities()
