"""Unit tests for shared crypto module."""

import pytest
import time
from crypto import (
    generate_nonce,
    get_timestamp,
    create_signature,
    verify_signature,
    sign_message,
    verify_message,
    MAX_MESSAGE_AGE
)


class TestNonce:
    """Tests for nonce generation."""

    def test_generate_nonce_returns_string(self):
        nonce = generate_nonce()
        assert isinstance(nonce, str)

    def test_generate_nonce_unique(self):
        nonces = [generate_nonce() for _ in range(100)]
        assert len(set(nonces)) == 100  # All unique

    def test_generate_nonce_format(self):
        nonce = generate_nonce()
        # UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        assert len(nonce) == 36
        assert nonce.count('-') == 4


class TestTimestamp:
    """Tests for timestamp generation."""

    def test_get_timestamp_returns_int(self):
        ts = get_timestamp()
        assert isinstance(ts, int)

    def test_get_timestamp_reasonable_value(self):
        ts = get_timestamp()
        # Should be within last few seconds
        assert abs(ts - int(time.time())) < 2


class TestSignature:
    """Tests for signature creation and verification."""

    def test_create_signature_returns_hex_string(self):
        sig = create_signature(
            "secret",
            "command",
            1234567890,
            "nonce123",
            {"key": "value"}
        )
        assert isinstance(sig, str)
        assert all(c in '0123456789abcdef' for c in sig)
        assert len(sig) == 64  # SHA256 hex = 64 chars

    def test_signature_deterministic(self):
        kwargs = {
            "shared_secret": "secret",
            "msg_type": "command",
            "timestamp": 1234567890,
            "nonce": "nonce123",
            "payload": {"key": "value"}
        }
        sig1 = create_signature(**kwargs)
        sig2 = create_signature(**kwargs)
        assert sig1 == sig2

    def test_signature_changes_with_secret(self):
        kwargs = {
            "msg_type": "command",
            "timestamp": 1234567890,
            "nonce": "nonce123",
            "payload": {"key": "value"}
        }
        sig1 = create_signature(shared_secret="secret1", **kwargs)
        sig2 = create_signature(shared_secret="secret2", **kwargs)
        assert sig1 != sig2

    def test_signature_changes_with_payload(self):
        kwargs = {
            "shared_secret": "secret",
            "msg_type": "command",
            "timestamp": 1234567890,
            "nonce": "nonce123",
        }
        sig1 = create_signature(**kwargs, payload={"key": "value1"})
        sig2 = create_signature(**kwargs, payload={"key": "value2"})
        assert sig1 != sig2


class TestVerifySignature:
    """Tests for signature verification."""

    def test_verify_valid_signature(self):
        secret = "test_secret"
        msg_type = "command"
        timestamp = get_timestamp()
        nonce = generate_nonce()
        payload = {"command": "ls -la"}

        sig = create_signature(secret, msg_type, timestamp, nonce, payload)
        is_valid, error = verify_signature(
            secret, msg_type, timestamp, nonce, payload, sig
        )
        assert is_valid is True
        assert error is None

    def test_verify_invalid_signature(self):
        secret = "test_secret"
        msg_type = "command"
        timestamp = get_timestamp()
        nonce = generate_nonce()
        payload = {"command": "ls -la"}

        is_valid, error = verify_signature(
            secret, msg_type, timestamp, nonce, payload, "invalid_signature"
        )
        assert is_valid is False
        assert error == "Invalid signature"

    def test_verify_wrong_secret(self):
        msg_type = "command"
        timestamp = get_timestamp()
        nonce = generate_nonce()
        payload = {"command": "ls -la"}

        sig = create_signature("secret1", msg_type, timestamp, nonce, payload)
        is_valid, error = verify_signature(
            "secret2", msg_type, timestamp, nonce, payload, sig
        )
        assert is_valid is False

    def test_verify_expired_timestamp(self):
        secret = "test_secret"
        msg_type = "command"
        old_timestamp = get_timestamp() - MAX_MESSAGE_AGE - 100
        nonce = generate_nonce()
        payload = {"command": "ls -la"}

        sig = create_signature(secret, msg_type, old_timestamp, nonce, payload)
        is_valid, error = verify_signature(
            secret, msg_type, old_timestamp, nonce, payload, sig
        )
        assert is_valid is False
        assert "expired" in error.lower()

    def test_verify_skip_timestamp_check(self):
        secret = "test_secret"
        msg_type = "command"
        old_timestamp = get_timestamp() - MAX_MESSAGE_AGE - 100
        nonce = generate_nonce()
        payload = {"command": "ls -la"}

        sig = create_signature(secret, msg_type, old_timestamp, nonce, payload)
        is_valid, error = verify_signature(
            secret, msg_type, old_timestamp, nonce, payload, sig,
            check_timestamp=False
        )
        assert is_valid is True


class TestSignMessage:
    """Tests for complete message signing."""

    def test_sign_message_structure(self):
        msg = sign_message("secret", "command", {"key": "value"})

        assert "type" in msg
        assert "payload" in msg
        assert "timestamp" in msg
        assert "nonce" in msg
        assert "signature" in msg

        assert msg["type"] == "command"
        assert msg["payload"] == {"key": "value"}

    def test_sign_message_verifiable(self):
        secret = "test_secret"
        msg = sign_message(secret, "upload", {"path": "/tmp/file"})

        is_valid, error = verify_message(secret, msg)
        assert is_valid is True


class TestVerifyMessage:
    """Tests for complete message verification."""

    def test_verify_valid_message(self):
        secret = "test_secret"
        msg = sign_message(secret, "download", {"path": "/tmp/file"})

        is_valid, error = verify_message(secret, msg)
        assert is_valid is True
        assert error is None

    def test_verify_missing_field(self):
        msg = {
            "type": "command",
            "payload": {},
            # missing timestamp, nonce, signature
        }

        is_valid, error = verify_message("secret", msg)
        assert is_valid is False
        assert "Missing required field" in error

    def test_verify_tampered_payload(self):
        secret = "test_secret"
        msg = sign_message(secret, "command", {"original": "value"})
        msg["payload"]["original"] = "tampered"

        is_valid, error = verify_message(secret, msg)
        assert is_valid is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
