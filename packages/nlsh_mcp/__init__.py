"""nlsh Remote MCP Server.

Provides MCP tools for remote command execution, file upload/download,
and working directory management via SSH tunnel to nlsh-remote.

This package implements a chain-of-trust security model:
- Verifies incoming messages signed by nlsh with nlsh's public key
- Re-signs outgoing messages to nlsh_remote with MCP server's private key
"""

__version__ = "1.0.0"
