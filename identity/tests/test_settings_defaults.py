"""Settings that must be safe when the environment does not say otherwise."""

import importlib
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured

from profile_identity_project import settings as project_settings


def _reload_settings():
    # load_dotenv would read a developer's local .env and hide the default.
    with patch("dotenv.load_dotenv"):
        return importlib.reload(project_settings)


@pytest.fixture(autouse=True)
def restore_settings_module(monkeypatch):
    # Settings refuse to load without a key when DEBUG is off.
    monkeypatch.setenv("SECRET_KEY", "settings-test-key")
    yield
    monkeypatch.undo()
    importlib.reload(project_settings)


def test_debug_is_off_when_the_variable_is_missing(monkeypatch):
    monkeypatch.delenv("DEBUG", raising=False)

    assert _reload_settings().DEBUG is False


@pytest.mark.parametrize("value", ["False", "false", "0", ""])
def test_debug_is_off_for_any_value_other_than_true(monkeypatch, value):
    monkeypatch.setenv("DEBUG", value)

    assert _reload_settings().DEBUG is False


def test_debug_can_still_be_turned_on_explicitly(monkeypatch):
    monkeypatch.setenv("DEBUG", "True")

    assert _reload_settings().DEBUG is True


def test_secret_key_is_required_when_debug_is_off(monkeypatch):
    monkeypatch.delenv("SECRET_KEY")
    monkeypatch.setenv("DEBUG", "False")

    with pytest.raises(ImproperlyConfigured, match="SECRET_KEY"):
        _reload_settings()


def test_empty_secret_key_is_treated_as_missing(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "")
    monkeypatch.setenv("DEBUG", "False")

    with pytest.raises(ImproperlyConfigured):
        _reload_settings()


def test_debug_falls_back_to_a_development_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY")
    monkeypatch.setenv("DEBUG", "True")

    assert _reload_settings().SECRET_KEY == "profile-identity-dev-secret"


def test_jwt_and_mfa_keys_follow_the_configured_secret_key(monkeypatch):
    monkeypatch.setenv("DEBUG", "False")
    monkeypatch.delenv("JWT_SIGNING_KEY", raising=False)
    monkeypatch.delenv("MFA_SECRET_ENCRYPTION_KEY", raising=False)

    loaded = _reload_settings()

    assert (
        loaded.JWT_SIGNING_KEY
        == loaded.MFA_SECRET_ENCRYPTION_KEY
        == "settings-test-key"
    )
