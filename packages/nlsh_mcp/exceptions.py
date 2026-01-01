"""Custom exceptions for nlsh-mcp server."""


class NlshMcpError(Exception):
    """Base exception for nlsh-mcp server."""
    pass


class NotConnectedError(NlshMcpError):
    """Raised when an operation requires a connection but none exists."""
    pass


class ConnectionFailedError(NlshMcpError):
    """Raised when connection to remote server fails."""

    def __init__(self, message: str, host: str = "", port: int = 0):
        super().__init__(message)
        self.host = host
        self.port = port


class RemoteExecutionError(NlshMcpError):
    """Raised when remote command execution fails."""

    def __init__(self, message: str, returncode: int = -1, stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class FileTransferError(NlshMcpError):
    """Raised when file upload/download fails."""

    def __init__(self, message: str, path: str = ""):
        super().__init__(message)
        self.path = path


class AuthenticationError(NlshMcpError):
    """Raised when signature verification fails."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message)


class ConfigurationError(NlshMcpError):
    """Raised when configuration is invalid or missing."""

    def __init__(self, message: str, missing_key: str = ""):
        super().__init__(message)
        self.missing_key = missing_key
