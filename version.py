"""Version information."""

__version__ = "0.0.1"


def get_version_header() -> str:
    """Get formatted version string for HTTP header."""
    return f"{__version__}"
