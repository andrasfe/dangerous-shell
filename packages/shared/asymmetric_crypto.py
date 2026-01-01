"""Ed25519 asymmetric message signing and verification for nlsh protocol.

This module implements a chain-of-trust security model using Ed25519 signatures:
- nlsh signs with its private key
- nlsh_mcp verifies with nlsh's public key, then re-signs with its own private key
- nlsh_remote verifies with nlsh_mcp's public key

Ed25519 provides:
- Fast signing and verification
- Small signatures (64 bytes)
- High security (128-bit security level)
"""

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from nacl.signing import SigningKey, VerifyKey
from nacl.encoding import HexEncoder, RawEncoder
from nacl.exceptions import BadSignatureError


# Maximum age of a message in seconds (prevents replay attacks)
MAX_MESSAGE_AGE = 300  # 5 minutes


class KeyLoadError(Exception):
    """Error loading a key from file."""
    pass


class SignatureError(Exception):
    """Error with signature creation or verification."""
    pass


def generate_nonce() -> str:
    """Generate a unique nonce for message signing."""
    return str(uuid.uuid4())


def get_timestamp() -> int:
    """Get current Unix timestamp."""
    return int(time.time())


def generate_keypair() -> Tuple[SigningKey, VerifyKey]:
    """Generate a new Ed25519 keypair.

    Returns:
        Tuple of (private_key, public_key)
    """
    private_key = SigningKey.generate()
    public_key = private_key.verify_key
    return private_key, public_key


def save_private_key(private_key: SigningKey, path: Union[str, Path]) -> None:
    """Save a private key to file in hex format.

    Args:
        private_key: The Ed25519 signing key
        path: Path to save the key
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Save as hex for readability and easy handling
    key_hex = private_key.encode(encoder=HexEncoder).decode('utf-8')
    path.write_text(key_hex)

    # Secure the file permissions (owner read/write only)
    path.chmod(0o600)


def save_public_key(public_key: VerifyKey, path: Union[str, Path]) -> None:
    """Save a public key to file in hex format.

    Args:
        public_key: The Ed25519 verify key
        path: Path to save the key
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    key_hex = public_key.encode(encoder=HexEncoder).decode('utf-8')
    path.write_text(key_hex)


def load_private_key(path: Union[str, Path]) -> SigningKey:
    """Load a private key from file.

    Args:
        path: Path to the key file (hex format)

    Returns:
        Ed25519 signing key

    Raises:
        KeyLoadError: If key cannot be loaded
    """
    path = Path(path).expanduser()
    try:
        key_hex = path.read_text().strip()
        return SigningKey(key_hex, encoder=HexEncoder)
    except FileNotFoundError:
        raise KeyLoadError(f"Private key not found: {path}")
    except Exception as e:
        raise KeyLoadError(f"Failed to load private key from {path}: {e}")


def load_public_key(path: Union[str, Path]) -> VerifyKey:
    """Load a public key from file.

    Args:
        path: Path to the key file (hex format)

    Returns:
        Ed25519 verify key

    Raises:
        KeyLoadError: If key cannot be loaded
    """
    path = Path(path).expanduser()
    try:
        key_hex = path.read_text().strip()
        return VerifyKey(key_hex, encoder=HexEncoder)
    except FileNotFoundError:
        raise KeyLoadError(f"Public key not found: {path}")
    except Exception as e:
        raise KeyLoadError(f"Failed to load public key from {path}: {e}")


def create_canonical_message(
    msg_type: str,
    timestamp: int,
    nonce: str,
    payload: Dict[str, Any]
) -> bytes:
    """Create the canonical message bytes to sign.

    Args:
        msg_type: Message type (command, upload, download, response)
        timestamp: Unix timestamp
        nonce: Unique nonce
        payload: Message payload dict

    Returns:
        UTF-8 encoded canonical message
    """
    # Convert enum to its value if needed
    if hasattr(msg_type, 'value'):
        msg_type = msg_type.value

    # Create canonical string (same format as HMAC version for consistency)
    payload_str = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    message = f"{msg_type}:{timestamp}:{nonce}:{payload_str}"
    return message.encode('utf-8')


def create_signature(
    private_key: SigningKey,
    msg_type: str,
    timestamp: int,
    nonce: str,
    payload: Dict[str, Any]
) -> str:
    """Create Ed25519 signature for a message.

    Args:
        private_key: Ed25519 signing key
        msg_type: Message type
        timestamp: Unix timestamp
        nonce: Unique nonce
        payload: Message payload dict

    Returns:
        Hex-encoded Ed25519 signature
    """
    message = create_canonical_message(msg_type, timestamp, nonce, payload)
    signed = private_key.sign(message)
    # Return just the signature, not the message
    return signed.signature.hex()


def verify_signature(
    public_key: VerifyKey,
    msg_type: str,
    timestamp: int,
    nonce: str,
    payload: Dict[str, Any],
    signature: str,
    check_timestamp: bool = True
) -> Tuple[bool, Optional[str]]:
    """Verify Ed25519 signature of a message.

    Args:
        public_key: Ed25519 verify key
        msg_type: Message type
        timestamp: Unix timestamp from message
        nonce: Nonce from message
        payload: Message payload dict
        signature: Hex-encoded signature to verify
        check_timestamp: Whether to check message age

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check timestamp age
    if check_timestamp:
        current_time = get_timestamp()
        if abs(current_time - timestamp) > MAX_MESSAGE_AGE:
            return False, f"Message expired (age: {abs(current_time - timestamp)}s)"

    # Verify signature
    try:
        message = create_canonical_message(msg_type, timestamp, nonce, payload)
        signature_bytes = bytes.fromhex(signature)
        public_key.verify(message, signature_bytes)
        return True, None
    except BadSignatureError:
        return False, "Invalid signature"
    except ValueError as e:
        return False, f"Invalid signature format: {e}"


def sign_message(private_key: SigningKey, msg_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a signed message ready for transmission.

    Args:
        private_key: Ed25519 signing key
        msg_type: Message type
        payload: Message payload

    Returns:
        Complete signed message dict
    """
    timestamp = get_timestamp()
    nonce = generate_nonce()
    signature = create_signature(private_key, msg_type, timestamp, nonce, payload)

    return {
        "type": msg_type,
        "payload": payload,
        "timestamp": timestamp,
        "nonce": nonce,
        "signature": signature
    }


def verify_message(public_key: VerifyKey, message: Dict[str, Any], check_timestamp: bool = True) -> Tuple[bool, Optional[str]]:
    """Verify a received message.

    Args:
        public_key: Ed25519 verify key
        message: The received message dict
        check_timestamp: Whether to check message age

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        msg_type = message["type"]
        payload = message["payload"]
        timestamp = message["timestamp"]
        nonce = message["nonce"]
        signature = message["signature"]
    except KeyError as e:
        return False, f"Missing required field: {e}"

    return verify_signature(
        public_key, msg_type, timestamp, nonce, payload, signature,
        check_timestamp=check_timestamp
    )


def re_sign_message(
    original_message: Dict[str, Any],
    new_private_key: SigningKey
) -> Dict[str, Any]:
    """Re-sign a message with a new private key.

    Used in chain-of-trust: MCP server verifies incoming message,
    then re-signs with its own key before forwarding to nlsh_remote.

    Args:
        original_message: The verified incoming message
        new_private_key: The new signing key

    Returns:
        New signed message with same payload but new signature
    """
    return sign_message(
        new_private_key,
        original_message["type"],
        original_message["payload"]
    )


def get_public_key_hex(private_key: SigningKey) -> str:
    """Get the hex-encoded public key from a private key.

    Args:
        private_key: Ed25519 signing key

    Returns:
        Hex-encoded public key
    """
    return private_key.verify_key.encode(encoder=HexEncoder).decode('utf-8')


def public_key_from_hex(hex_key: str) -> VerifyKey:
    """Load a public key from hex string.

    Args:
        hex_key: Hex-encoded public key

    Returns:
        Ed25519 verify key
    """
    return VerifyKey(hex_key, encoder=HexEncoder)


def private_key_from_hex(hex_key: str) -> SigningKey:
    """Load a private key from hex string.

    Args:
        hex_key: Hex-encoded private key

    Returns:
        Ed25519 signing key
    """
    return SigningKey(hex_key, encoder=HexEncoder)
