"""Tests for EZVIZ API region selection."""

from custom_components.ezviz_plus.config_flow import _login_api_host


def test_login_api_host_prefers_redirected_region() -> None:
    """Persist the API host returned by EZVIZ after a regional redirect."""
    token = {"api_url": "apiisa.ezvizlife.com"}

    assert _login_api_host(token, "apiieu.ezvizlife.com") == "apiisa.ezvizlife.com"


def test_login_api_host_normalizes_and_falls_back() -> None:
    """Normalize returned hosts and retain the selected host when absent."""
    assert (
        _login_api_host(
            {"api_url": " https://apiisa.ezvizlife.com/ "},
            "apiieu.ezvizlife.com",
        )
        == "apiisa.ezvizlife.com"
    )
    assert _login_api_host({}, "apiieu.ezvizlife.com") == "apiieu.ezvizlife.com"