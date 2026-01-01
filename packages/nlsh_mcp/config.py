"""Configuration for nlsh-mcp server."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .exceptions import ConfigurationError


@dataclass
class MCPConfig:
    """Configuration for the MCP server."""
    # Key paths
    mcp_private_key_path: Path
    nlsh_public_key_path: Path

    # Remote server connection
    remote_host: str
    remote_port: int

    # Timeouts
    connection_timeout: float = 30.0
    command_timeout: int = 300

    # Server identification
    server_name: str = "nlsh_remote_mcp"
    server_version: str = "1.0.0"


def get_config() -> MCPConfig:
    """Load configuration from environment.

    Required environment variables:
        NLSH_MCP_PRIVATE_KEY_PATH: Path to MCP server's Ed25519 private key
        NLSH_PUBLIC_KEY_PATH: Path to nlsh client's Ed25519 public key

    Optional environment variables:
        NLSH_REMOTE_HOST: Remote server host (default: 127.0.0.1)
        NLSH_REMOTE_PORT: Remote server port (default: 8765)
        NLSH_CONNECTION_TIMEOUT: Connection timeout in seconds (default: 30.0)
        NLSH_COMMAND_TIMEOUT: Command timeout in seconds (default: 300)
        NLSH_MCP_SERVER_NAME: Server name (default: nlsh_remote_mcp)
        NLSH_MCP_VERSION: Server version (default: 1.0.0)

    Returns:
        MCPConfig with loaded values

    Raises:
        ConfigurationError: If required environment variables are missing
    """
    # Load .env file if it exists
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)

    # Also try parent directory .env
    parent_env = Path(__file__).parent.parent / ".env"
    if parent_env.exists():
        load_dotenv(parent_env)

    # Required: MCP private key path
    mcp_private_key_path = os.getenv("NLSH_MCP_PRIVATE_KEY_PATH")
    if not mcp_private_key_path:
        raise ConfigurationError(
            "NLSH_MCP_PRIVATE_KEY_PATH environment variable is required. "
            "This should point to the MCP server's Ed25519 private key file. "
            "Generate keys with: python -m shared.keygen mcp",
            missing_key="NLSH_MCP_PRIVATE_KEY_PATH"
        )

    # Required: nlsh public key path
    nlsh_public_key_path = os.getenv("NLSH_PUBLIC_KEY_PATH")
    if not nlsh_public_key_path:
        raise ConfigurationError(
            "NLSH_PUBLIC_KEY_PATH environment variable is required. "
            "This should point to the nlsh client's Ed25519 public key file. "
            "The nlsh public key should be copied from the nlsh client machine.",
            missing_key="NLSH_PUBLIC_KEY_PATH"
        )

    return MCPConfig(
        mcp_private_key_path=Path(mcp_private_key_path).expanduser(),
        nlsh_public_key_path=Path(nlsh_public_key_path).expanduser(),
        remote_host=os.getenv("NLSH_REMOTE_HOST", "127.0.0.1"),
        remote_port=int(os.getenv("NLSH_REMOTE_PORT", "8765")),
        connection_timeout=float(os.getenv("NLSH_CONNECTION_TIMEOUT", "30.0")),
        command_timeout=int(os.getenv("NLSH_COMMAND_TIMEOUT", "300")),
        server_name=os.getenv("NLSH_MCP_SERVER_NAME", "nlsh_remote_mcp"),
        server_version=os.getenv("NLSH_MCP_VERSION", "1.0.0"),
    )


def validate_config(config: MCPConfig) -> None:
    """Validate configuration paths exist.

    Args:
        config: The configuration to validate

    Raises:
        ConfigurationError: If required files don't exist
    """
    if not config.mcp_private_key_path.exists():
        raise ConfigurationError(
            f"MCP private key not found at {config.mcp_private_key_path}. "
            "Generate keys with: python -m shared.keygen mcp",
            missing_key="NLSH_MCP_PRIVATE_KEY_PATH"
        )

    if not config.nlsh_public_key_path.exists():
        raise ConfigurationError(
            f"nlsh public key not found at {config.nlsh_public_key_path}. "
            "Copy the nlsh_public.key from the nlsh client machine.",
            missing_key="NLSH_PUBLIC_KEY_PATH"
        )
