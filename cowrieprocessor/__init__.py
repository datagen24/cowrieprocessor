"""Core package scaffolding for the refactored Cowrie processor pipeline."""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["get_version"]


def get_version() -> str:
    """Return the installed package version or a development marker."""
    try:
        return version("cowrieprocessor")
    except PackageNotFoundError:
        return "0.0.0-dev"
