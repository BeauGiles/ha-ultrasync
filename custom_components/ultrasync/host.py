"""Helpers for the panel host setting.

The host can carry a user name and password for basic authentication, as a
URL (http://user:password@panel) or without a scheme (user:password@panel).
The requests library sends them in both forms. The entry title is shown in
lists and logs and is not treated as a secret, so it must not show them.
"""
from urllib.parse import urlparse


def _netloc(host: str) -> str:
    """Return the network location of the host, with any user information."""
    host = host.strip()
    return urlparse(host if "://" in host else f"//{host}").netloc


def host_has_credentials(host: str) -> bool:
    """Return true if the host carries a user name or password."""
    try:
        return "@" in _netloc(host)
    except ValueError:
        # Not a valid host; treat anything with an "@" as carrying them
        return "@" in host


def host_title(host: str) -> str:
    """Return the host as a title, without any user name and password."""
    if not host_has_credentials(host):
        return host

    try:
        return _netloc(host).rpartition("@")[2] or "UltraSync"
    except ValueError:
        # Not a valid host; it can not be shown safely
        return "UltraSync"
