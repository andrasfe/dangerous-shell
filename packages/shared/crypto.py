"""HMAC-SHA256 message signing and verification for nlsh protocol."""

import hmac
import hashlib
import json
import time
import uuid
from typing import Any


# Maximum age of a message in seconds (prevents replay attacks)
MAX_MESSAGE_AGE = 300  # 5 minutes


def generate_nonce() -> str:
    """Generate a unique nonce for message signing."""
    return str(uuid.uuid4())


def get_timestamp() -> int:
    """Get current Unix timestamp."""
    return int(time.time())


def create_signature(
    shared_secret: str,
    msg_type: str,
    timestamp: int,
    nonce: str,
    payload: dict[str, Any]
) -> str:
    """Create HMAC-SHA256 signature for a message.

    Args:
        shared_secret: The shared secret key
        msg_type: Message type (command, upload, download, response)
        timestamp: Unix timestamp
        nonce: Unique nonce
        payload: Message payload dict

    Returns:
        Hex-encoded HMAC-SHA256 signature
    """
    # Convert enum to its value if needed
    if hasattr(msg_type, 'value'):
        msg_type = msg_type.value

    # Create canonical string to sign
    payload_str = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    message = f"{msg_type}:{timestamp}:{nonce}:{payload_str}"

    # Create HMAC-SHA256 signature
    signature = hmac.new(
        shared_secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return signature


def verify_signature(
    shared_secret: str,
    msg_type: str,
    timestamp: int,
    nonce: str,
    payload: dict[str, Any],
    signature: str,
    check_timestamp: bool = True
) -> tuple[bool, str | None]:
    """Verify HMAC-SHA256 signature of a message.

    Args:
        shared_secret: The shared secret key
        msg_type: Message type
        timestamp: Unix timestamp from message
        nonce: Nonce from message
        payload: Message payload dict
        signature: Signature to verify
        check_timestamp: Whether to check message age

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check timestamp age
    if check_timestamp:
        current_time = get_timestamp()
        if abs(current_time - timestamp) > MAX_MESSAGE_AGE:
            return False, f"Message expired (age: {abs(current_time - timestamp)}s)"

    # Compute expected signature
    expected_signature = create_signature(
        shared_secret, msg_type, timestamp, nonce, payload
    )

    # Constant-time comparison to prevent timing attacks
    if hmac.compare_digest(expected_signature, signature):
        return True, None
    else:
        return False, "Invalid signature"


def sign_message(shared_secret: str, msg_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create a signed message ready for transmission.

    Args:
        shared_secret: The shared secret key
        msg_type: Message type
        payload: Message payload

    Returns:
        Complete signed message dict
    """
    timestamp = get_timestamp()
    nonce = generate_nonce()
    signature = create_signature(shared_secret, msg_type, timestamp, nonce, payload)

    return {
        "type": msg_type,
        "payload": payload,
        "timestamp": timestamp,
        "nonce": nonce,
        "signature": signature
    }


def verify_message(shared_secret: str, message: dict[str, Any]) -> tuple[bool, str | None]:
    """Verify a received message.

    Args:
        shared_secret: The shared secret key
        message: The received message dict

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
        shared_secret, msg_type, timestamp, nonce, payload, signature
    )
