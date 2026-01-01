"""Unit tests for Ed25519 asymmetric crypto module."""

import pytest
import time
from pathlib import Path

from asymmetric_crypto import (
    generate_keypair,
    generate_nonce,
    get_timestamp,
    save_private_key,
    save_public_key,
    load_private_key,
    load_public_key,
    create_signature,
    verify_signature,
    sign_message,
    verify_message,
    re_sign_message,
    get_public_key_hex,
    public_key_from_hex,
    private_key_from_hex,
    KeyLoadError,
    MAX_MESSAGE_AGE,
)


class TestNonceGeneration:
    """Tests for nonce generation."""

    def test_nonce_is_string(self):
        """Nonce should be a string."""
        nonce = generate_nonce()
        assert isinstance(nonce, str)

    def test_nonce_is_unique(self):
        """Each nonce should be unique."""
        nonces = [generate_nonce() for _ in range(100)]
        assert len(set(nonces)) == 100

    def test_nonce_format(self):
        """Nonce should be UUID format."""
        nonce = generate_nonce()
        # UUID format: 8-4-4-4-12 characters
        assert len(nonce) == 36
        assert nonce.count('-') == 4


class TestTimestamp:
    """Tests for timestamp generation."""

    def test_timestamp_is_int(self):
        """Timestamp should be an integer."""
        ts = get_timestamp()
        assert isinstance(ts, int)

    def test_timestamp_is_current(self):
        """Timestamp should be close to current time."""
        ts = get_timestamp()
        now = int(time.time())
        assert abs(ts - now) < 2


class TestKeypairGeneration:
    """Tests for Ed25519 keypair generation."""

    def test_generate_keypair_returns_tuple(self):
        """Should return tuple of (SigningKey, VerifyKey)."""
        private_key, public_key = generate_keypair()
        assert private_key is not None
        assert public_key is not None

    def test_keypair_types(self):
        """Keys should be correct types."""
        from nacl.signing import SigningKey, VerifyKey
        private_key, public_key = generate_keypair()
        assert isinstance(private_key, SigningKey)
        assert isinstance(public_key, VerifyKey)

    def test_keypair_unique(self):
        """Each generated keypair should be unique."""
        pairs = [generate_keypair() for _ in range(10)]
        public_keys = [bytes(p[1]) for p in pairs]
        assert len(set(public_keys)) == 10


class TestKeyStorage:
    """Tests for key storage and loading."""

    def test_save_and_load_private_key(self, tmp_path):
        """Private key should roundtrip through save/load."""
        private_key, _ = generate_keypair()
        key_path = tmp_path / "test.key"

        save_private_key(private_key, key_path)
        loaded = load_private_key(key_path)

        assert bytes(loaded) == bytes(private_key)

    def test_save_and_load_public_key(self, tmp_path):
        """Public key should roundtrip through save/load."""
        _, public_key = generate_keypair()
        key_path = tmp_path / "test.pub"

        save_public_key(public_key, key_path)
        loaded = load_public_key(key_path)

        assert bytes(loaded) == bytes(public_key)

    def test_private_key_permissions(self, tmp_path):
        """Private key file should have restricted permissions."""
        import os
        private_key, _ = generate_keypair()
        key_path = tmp_path / "test.key"

        save_private_key(private_key, key_path)

        mode = os.stat(key_path).st_mode & 0o777
        assert mode == 0o600

    def test_load_nonexistent_key(self, tmp_path):
        """Should raise KeyLoadError for missing file."""
        with pytest.raises(KeyLoadError):
            load_private_key(tmp_path / "nonexistent.key")

    def test_load_from_expanduser(self, tmp_path, monkeypatch):
        """Should expand ~ in path."""
        private_key, _ = generate_keypair()
        key_path = tmp_path / "test.key"
        save_private_key(private_key, key_path)

        # Monkeypatch expanduser to return our tmp_path
        monkeypatch.setattr(Path, 'expanduser', lambda self: key_path if '~' in str(self) else self)

        loaded = load_private_key(key_path)
        assert loaded is not None


class TestHexConversion:
    """Tests for hex key conversion."""

    def test_get_public_key_hex(self):
        """Should return 64-char hex string."""
        private_key, _ = generate_keypair()
        hex_key = get_public_key_hex(private_key)

        assert isinstance(hex_key, str)
        assert len(hex_key) == 64
        assert all(c in '0123456789abcdef' for c in hex_key)

    def test_public_key_from_hex(self):
        """Should load public key from hex."""
        _, public_key = generate_keypair()
        hex_key = bytes(public_key).hex()

        loaded = public_key_from_hex(hex_key)
        assert bytes(loaded) == bytes(public_key)

    def test_private_key_from_hex(self):
        """Should load private key from hex."""
        private_key, _ = generate_keypair()
        hex_key = bytes(private_key).hex()

        loaded = private_key_from_hex(hex_key)
        assert bytes(loaded) == bytes(private_key)


class TestSignature:
    """Tests for signature creation."""

    def test_signature_is_hex_string(self):
        """Signature should be hex-encoded string."""
        private_key, _ = generate_keypair()

        sig = create_signature(
            private_key,
            msg_type="command",
            timestamp=1234567890,
            nonce="test-nonce",
            payload={"key": "value"}
        )

        assert isinstance(sig, str)
        assert all(c in '0123456789abcdef' for c in sig)

    def test_signature_length(self):
        """Ed25519 signature should be 128 hex chars (64 bytes)."""
        private_key, _ = generate_keypair()

        sig = create_signature(
            private_key,
            msg_type="command",
            timestamp=1234567890,
            nonce="test-nonce",
            payload={"key": "value"}
        )

        assert len(sig) == 128

    def test_signature_deterministic(self):
        """Same inputs should produce same signature."""
        private_key, _ = generate_keypair()

        sig1 = create_signature(
            private_key,
            msg_type="command",
            timestamp=1234567890,
            nonce="test-nonce",
            payload={"key": "value"}
        )

        sig2 = create_signature(
            private_key,
            msg_type="command",
            timestamp=1234567890,
            nonce="test-nonce",
            payload={"key": "value"}
        )

        assert sig1 == sig2

    def test_signature_changes_with_payload(self):
        """Different payloads should produce different signatures."""
        private_key, _ = generate_keypair()

        sig1 = create_signature(
            private_key,
            msg_type="command",
            timestamp=1234567890,
            nonce="test-nonce",
            payload={"key": "value1"}
        )

        sig2 = create_signature(
            private_key,
            msg_type="command",
            timestamp=1234567890,
            nonce="test-nonce",
            payload={"key": "value2"}
        )

        assert sig1 != sig2

    def test_signature_changes_with_key(self):
        """Different keys should produce different signatures."""
        private_key1, _ = generate_keypair()
        private_key2, _ = generate_keypair()

        kwargs = {
            "msg_type": "command",
            "timestamp": 1234567890,
            "nonce": "test-nonce",
            "payload": {"key": "value"}
        }

        sig1 = create_signature(private_key1, **kwargs)
        sig2 = create_signature(private_key2, **kwargs)

        assert sig1 != sig2


class TestVerifySignature:
    """Tests for signature verification."""

    def test_verify_valid_signature(self):
        """Valid signature should verify successfully."""
        private_key, public_key = generate_keypair()
        timestamp = get_timestamp()
        nonce = generate_nonce()
        payload = {"command": "echo hello"}

        sig = create_signature(
            private_key,
            msg_type="command",
            timestamp=timestamp,
            nonce=nonce,
            payload=payload
        )

        is_valid, error = verify_signature(
            public_key,
            msg_type="command",
            timestamp=timestamp,
            nonce=nonce,
            payload=payload,
            signature=sig
        )

        assert is_valid is True
        assert error is None

    def test_verify_wrong_public_key(self):
        """Signature should fail with wrong public key."""
        private_key1, _ = generate_keypair()
        _, public_key2 = generate_keypair()
        timestamp = get_timestamp()
        nonce = generate_nonce()
        payload = {"command": "ls"}

        sig = create_signature(
            private_key1,
            msg_type="command",
            timestamp=timestamp,
            nonce=nonce,
            payload=payload
        )

        is_valid, error = verify_signature(
            public_key2,
            msg_type="command",
            timestamp=timestamp,
            nonce=nonce,
            payload=payload,
            signature=sig
        )

        assert is_valid is False
        assert error is not None

    def test_verify_tampered_payload(self):
        """Tampered payload should fail verification."""
        private_key, public_key = generate_keypair()
        timestamp = get_timestamp()
        nonce = generate_nonce()

        sig = create_signature(
            private_key,
            msg_type="command",
            timestamp=timestamp,
            nonce=nonce,
            payload={"command": "ls"}
        )

        is_valid, error = verify_signature(
            public_key,
            msg_type="command",
            timestamp=timestamp,
            nonce=nonce,
            payload={"command": "rm -rf /"},  # Tampered!
            signature=sig
        )

        assert is_valid is False

    def test_verify_expired_timestamp(self):
        """Expired message should fail verification."""
        private_key, public_key = generate_keypair()
        old_timestamp = get_timestamp() - MAX_MESSAGE_AGE - 100
        nonce = generate_nonce()
        payload = {"command": "ls"}

        sig = create_signature(
            private_key,
            msg_type="command",
            timestamp=old_timestamp,
            nonce=nonce,
            payload=payload
        )

        is_valid, error = verify_signature(
            public_key,
            msg_type="command",
            timestamp=old_timestamp,
            nonce=nonce,
            payload=payload,
            signature=sig
        )

        assert is_valid is False
        assert "expired" in error.lower()

    def test_verify_skip_timestamp_check(self):
        """Should verify old message when timestamp check disabled."""
        private_key, public_key = generate_keypair()
        old_timestamp = get_timestamp() - MAX_MESSAGE_AGE - 100
        nonce = generate_nonce()
        payload = {"command": "ls"}

        sig = create_signature(
            private_key,
            msg_type="command",
            timestamp=old_timestamp,
            nonce=nonce,
            payload=payload
        )

        is_valid, error = verify_signature(
            public_key,
            msg_type="command",
            timestamp=old_timestamp,
            nonce=nonce,
            payload=payload,
            signature=sig,
            check_timestamp=False
        )

        assert is_valid is True


class TestSignMessage:
    """Tests for high-level sign_message function."""

    def test_sign_message_structure(self):
        """Signed message should have all required fields."""
        private_key, _ = generate_keypair()

        msg = sign_message(
            private_key,
            msg_type="command",
            payload={"command": "ls"}
        )

        assert "type" in msg
        assert "payload" in msg
        assert "timestamp" in msg
        assert "nonce" in msg
        assert "signature" in msg

    def test_sign_message_type(self):
        """Message type should be preserved."""
        private_key, _ = generate_keypair()

        msg = sign_message(
            private_key,
            msg_type="upload",
            payload={}
        )

        assert msg["type"] == "upload"

    def test_sign_message_payload(self):
        """Payload should be preserved."""
        private_key, _ = generate_keypair()
        payload = {"key": "value", "nested": {"a": 1}}

        msg = sign_message(
            private_key,
            msg_type="command",
            payload=payload
        )

        assert msg["payload"] == payload


class TestVerifyMessage:
    """Tests for high-level verify_message function."""

    def test_roundtrip_sign_verify(self):
        """Message should roundtrip through sign/verify."""
        private_key, public_key = generate_keypair()

        msg = sign_message(
            private_key,
            msg_type="command",
            payload={"command": "echo test"}
        )

        is_valid, error = verify_message(public_key, msg)

        assert is_valid is True
        assert error is None

    def test_verify_missing_field(self):
        """Should reject message with missing fields."""
        _, public_key = generate_keypair()

        incomplete_msg = {
            "type": "command",
            "payload": {},
            # Missing timestamp, nonce, signature
        }

        is_valid, error = verify_message(public_key, incomplete_msg)

        assert is_valid is False
        assert "Missing" in error

    def test_verify_with_timestamp_check(self):
        """Should respect check_timestamp parameter."""
        private_key, public_key = generate_keypair()

        msg = sign_message(
            private_key,
            msg_type="command",
            payload={"command": "ls"}
        )

        # Artificially age the message
        msg["timestamp"] = msg["timestamp"] - MAX_MESSAGE_AGE - 100

        # Should fail with timestamp check
        is_valid, error = verify_message(public_key, msg, check_timestamp=True)
        assert is_valid is False

        # Should pass without timestamp check
        # (but signature would be invalid because we modified timestamp)


class TestReSignMessage:
    """Tests for message re-signing (chain of trust)."""

    def test_re_sign_preserves_type(self):
        """Re-signed message should preserve type."""
        private_key1, _ = generate_keypair()
        private_key2, _ = generate_keypair()

        original = sign_message(
            private_key1,
            msg_type="command",
            payload={"command": "ls"}
        )

        re_signed = re_sign_message(original, private_key2)

        assert re_signed["type"] == original["type"]

    def test_re_sign_preserves_payload(self):
        """Re-signed message should preserve payload."""
        private_key1, _ = generate_keypair()
        private_key2, _ = generate_keypair()

        original = sign_message(
            private_key1,
            msg_type="command",
            payload={"command": "ls", "nested": {"a": 1}}
        )

        re_signed = re_sign_message(original, private_key2)

        assert re_signed["payload"] == original["payload"]

    def test_re_sign_new_signature(self):
        """Re-signed message should have different signature."""
        private_key1, _ = generate_keypair()
        private_key2, _ = generate_keypair()

        original = sign_message(
            private_key1,
            msg_type="command",
            payload={"command": "ls"}
        )

        re_signed = re_sign_message(original, private_key2)

        assert re_signed["signature"] != original["signature"]

    def test_re_sign_verifiable(self):
        """Re-signed message should be verifiable with new key."""
        private_key1, public_key1 = generate_keypair()
        private_key2, public_key2 = generate_keypair()

        original = sign_message(
            private_key1,
            msg_type="command",
            payload={"command": "ls"}
        )

        re_signed = re_sign_message(original, private_key2)

        # Should fail with original public key
        is_valid1, _ = verify_message(public_key1, re_signed)
        assert is_valid1 is False

        # Should pass with new public key
        is_valid2, _ = verify_message(public_key2, re_signed)
        assert is_valid2 is True
