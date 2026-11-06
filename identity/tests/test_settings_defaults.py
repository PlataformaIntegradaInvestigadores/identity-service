"""Settings that must be safe when the environment does not say otherwise."""

import importlib
from unittest.mock import patch

import pytest

from profile_identity_project import settings as project_settings


def _reload_settings():
    # load_dotenv would read a developer's local .env and hide the default.
    with patch("dotenv.load_dotenv"):
        return importlib.reload(project_settings)


@pytest.fixture(autouse=True)
def restore_settings_module():
    yield
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
