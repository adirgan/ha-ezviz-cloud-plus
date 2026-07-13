"""Tests for per-camera credential retrieval."""

from unittest.mock import MagicMock

from pyezvizapi.exceptions import EzvizAuthVerificationCode
import pytest

from custom_components.ezviz_plus.config_flow import (
    _get_cam_enc_key,
    _get_cam_verification_code,
)
from custom_components.ezviz_plus.const import ATTR_SERIAL


def test_camera_verification_code_uses_correct_sender_type() -> None:
    """Use sender type 3 only when submitting the one-time code."""
    client = MagicMock()
    client.get_cam_auth_code.return_value = "camera-code"
    data = {ATTR_SERIAL: "TEST123", "cloud_account_username": "user@example.com"}

    assert _get_cam_verification_code(data, client) == "camera-code"
    client.get_cam_auth_code.assert_called_once_with(
        "TEST123", msg_auth_code=None, sender_type=0
    )

    client.get_cam_auth_code.reset_mock()

    assert _get_cam_verification_code(data, client, "123456") == "camera-code"
    client.get_cam_auth_code.assert_called_once_with(
        "TEST123", msg_auth_code="123456", sender_type=3
    )


def test_camera_encryption_key_requests_matching_one_time_code() -> None:
    """Request a DEVICE_ENCRYPTION code when key retrieval requires elevation."""
    client = MagicMock()
    client.get_cam_key.side_effect = EzvizAuthVerificationCode()
    data = {ATTR_SERIAL: "TEST123", "cloud_account_username": "user@example.com"}

    with pytest.raises(EzvizAuthVerificationCode):
        _get_cam_enc_key(data, client)

    client.get_2fa_check_code.assert_called_once_with(
        username="user@example.com", biz_type="DEVICE_ENCRYPTION"
    )